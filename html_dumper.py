# -*- coding: utf-8 -*-

"""
Confluence-dumper is a Python project to export spaces and pages, excluding attachments.
"""

from __future__ import print_function
import sys
import codecs
import os
import shutil
from lxml import html
from lxml.etree import XMLSyntaxError

import utils
import settings


CONFLUENCE_DUMPER_VERSION = '1.1.0'
TITLE_OUTPUT = 'C O N F L U E N C E   D U M P E R  %s' % CONFLUENCE_DUMPER_VERSION


def error_print(*args, **kwargs):
    """ Wrapper for the print function which leads to stderr outputs.

    :param args: Not necessary.
    :param kwargs: Not necessary.
    """
    print(*args, file=sys.stderr, **kwargs)


def provide_unique_file_name(duplicate_file_names, file_matching, file_title, is_folder=False,
                             explicit_file_extension=None):
    """ Provides a unique AND sanitized file name for a given page title. """
    if file_title in file_matching:
        file_name = file_matching[file_title]
    else:
        file_name = utils.sanitize_for_filename(file_title)

        if is_folder:
            file_extension = None
        elif explicit_file_extension:
            file_extension = explicit_file_extension
        else:
            if '.' in file_name:
                file_name, file_extension = file_name.rsplit('.', 1)
            else:
                file_extension = None

        if file_name in duplicate_file_names:
            duplicate_file_names[file_name] += 1
            file_name = '%s_%d' % (file_name, duplicate_file_names[file_name])
        else:
            duplicate_file_names[file_name] = 0
            file_name = file_name

        if file_extension:
            file_name += '.%s' % file_extension

        file_matching[file_title] = file_name
    return file_name


def handle_html_references(html_content, page_duplicate_file_names, page_file_matching, depth=0):
    """ Repairs links in the page contents with local links.

    :param html_content: Confluence HTML content.
    :param page_duplicate_file_names: A dict in the structure {'<sanitized filename>': amount of duplicates}
    :param page_file_matching: A dict in the structure {'<page title>': '<used offline filename>'}
    :param depth: (optional) Hierarchy depth of the handled Confluence page.
    :returns: Fixed HTML content.
    """
    if html_content == "":
        return ""
    try:
        html_tree = html.fromstring(html_content)
    except XMLSyntaxError:
        print('%sWARNING: Could not parse HTML content of last page. Original content will be downloaded as it is.'
              % ('\t'*(depth+1)))
        return html_content

    # Fix links to other Confluence pages
    xpath_expr = '//a[contains(@href, "/display/")]'
    for link_element in html_tree.xpath(xpath_expr):
        if not link_element.get('class'):
            try:
                page_title = link_element.attrib['href'].split('/')[4]
            except:
                page_title = link_element.attrib['href'].split('/')[3]

            page_title = page_title.replace('+', ' ')
            decoded_page_title = utils.decode_url(page_title)
            offline_link = provide_unique_file_name(page_duplicate_file_names, page_file_matching, decoded_page_title,
                                                    explicit_file_extension='html')
            link_element.attrib['href'] = utils.encode_url(offline_link)

    # Fix links to other Confluence pages when page ids are used
    xpath_expr = '//a[contains(@href, "/pages/viewpage.action?pageId=")]'
    for link_element in html_tree.xpath(xpath_expr):
        if not link_element.get('class'):
            page_id = link_element.attrib['href'].split('/pages/viewpage.action?pageId=')[1]
            offline_link = '%s.html' % utils.sanitize_for_filename(page_id)
            link_element.attrib['href'] = utils.encode_url(offline_link)

    return html.tostring(html_tree)


def fetch_page_recursively(page_id, folder_path, download_folder, html_template, depth=0,
                           page_duplicate_file_names=None, page_file_matching=None):
    """ Fetches a Confluence page and its child pages (without attachments).

    :param page_id: Confluence page id.
    :param folder_path: Folder to place downloaded pages in.
    :param download_folder: Folder to place downloaded files in.
    :param html_template: HTML template used to export Confluence pages.
    :param depth: (optional) Hierarchy depth of the handled Confluence page.
    :param page_duplicate_file_names: A dict in the structure {'<sanitized page filename>': amount of duplicates}
    :param page_file_matching: A dict in the structure {'<page title>': '<used offline filename>'}
    :returns: Information about downloaded pages as a dict (None for exceptions)
    """
    if not page_duplicate_file_names:
        page_duplicate_file_names = {}
    if not page_file_matching:
        page_file_matching = {}

    page_url = '%s/wiki/rest/api/content/%s?expand=children.page,body.view.value' % (settings.CONFLUENCE_BASE_URL, page_id)
    try:
        response = utils.http_get(page_url, auth=settings.HTTP_AUTHENTICATION, headers=settings.HTTP_CUSTOM_HEADERS,
                                  verify_peer_certificate=settings.VERIFY_PEER_CERTIFICATE,
                                  proxies=settings.HTTP_PROXIES)
        page_content = response['body']['view']['value']
        if isinstance(page_content, bytes):
            page_content = page_content.decode('utf-8')

        page_title = response['title']
        print('%sPAGE: %s (%s)' % ('\t'*(depth+1), page_title, page_id))

        # Construct unique file name
        file_name = provide_unique_file_name(page_duplicate_file_names, page_file_matching, page_title,
                                             explicit_file_extension='html')

        # Remember this file and all children
        path_collection = {'file_path': file_name, 'page_title': page_title, 'child_pages': []}

        # Export HTML file
        page_content = handle_html_references(page_content, page_duplicate_file_names, page_file_matching,
                                              depth=depth + 1)
        file_path = f'{folder_path}/{file_name}'
        utils.write_html_2_file(file_path,page_title,page_content, html_template)
        # utils.write_html_2_file(file_path, page_title, page_content, html_template, replacements={})

        # Save another file with page id which forwards to the original one
        id_file_path = '%s/%s.html' % (folder_path, page_id)
        id_file_page_title = 'Forward to page %s' % page_title
        original_file_link = utils.encode_url(utils.sanitize_for_filename(file_name))
        id_file_page_content = settings.HTML_FORWARD_MESSAGE % (original_file_link, page_title)
        id_file_forward_header = '<meta http-equiv="refresh" content="0; url=%s" />' % original_file_link
        utils.write_html_2_file(id_file_path, id_file_page_title, id_file_page_content, html_template,
                                additional_headers=[id_file_forward_header])

        # Iterate through all child pages
        page_url = '%s/wiki/rest/api/content/%s/child/page?limit=25' % (settings.CONFLUENCE_BASE_URL, page_id)
        counter = 0
        while page_url:
            response = utils.http_get(page_url, auth=settings.HTTP_AUTHENTICATION, headers=settings.HTTP_CUSTOM_HEADERS,
                                      verify_peer_certificate=settings.VERIFY_PEER_CERTIFICATE,
                                      proxies=settings.HTTP_PROXIES)
            counter += len(response['results'])
            for child_page in response['results']:
                paths = fetch_page_recursively(child_page['id'], folder_path, download_folder, html_template,
                                               depth=depth+1, page_duplicate_file_names=page_duplicate_file_names,
                                               page_file_matching=page_file_matching)
                if paths:
                    path_collection['child_pages'].append(paths)

            if 'next' in response['_links'].keys():
                page_url = response['_links']['next']
                page_url = '%s%s' % (settings.CONFLUENCE_BASE_URL, page_url)
            else:
                page_url = None
        return path_collection

    except utils.ConfluenceException as e:
        error_print('%sERROR: %s' % ('\t'*(depth+1), e))
        return None


def create_html_index(index_content):
    """ Creates an HTML index (mainly to navigate through the exported pages).

    :param index_content: Dictionary which contains file paths, page titles and their children recursively.
    :returns: Content index as HTML.
    """
    file_path = utils.encode_url(index_content['file_path'])
    page_title = index_content['page_title']
    page_children = index_content['child_pages']

    html_content = '<a href="%s">%s</a>' % (utils.sanitize_for_filename(file_path), page_title)

    if len(page_children) > 0:
        html_content += '<ul>\n'
        for child in page_children:
            html_content += '\t<li>%s</li>\n' % create_html_index(child)
        html_content += '</ul>\n'

    return html_content


def print_welcome_output():
    """ Displays software title and some license information """
    print('\n\t %s' % TITLE_OUTPUT)
    print('\t %s\n' % ('='*len(TITLE_OUTPUT)))
    print('... a Python project to export spaces and pages (attachments excluded)\n')
    print('Copyright (c) Siemens AG, 2016\n')
    print('Authors:')
    print('  Thomas Maier <thomas.tm.maier@siemens.com>\n')
    print('This work is licensed under the terms of the MIT license.')
    print('See the LICENSE.md file in the top-level directory.\n\n')


def print_finished_output():
    """ Displays exit message (for successful export) """
    print('\n\nFinished!\n')


def main():
    """ Main function to start the confluence-dumper (without attachments). """

    # Configure console for unicode output via stdout/stderr

    # Welcome output
    print_welcome_output()

    # Delete old export
    if os.path.exists(settings.EXPORT_FOLDER):
        shutil.rmtree(settings.EXPORT_FOLDER)
    os.makedirs(settings.EXPORT_FOLDER)

    # Read HTML template
    template_file = open(settings.TEMPLATE_FILE)
    html_template = template_file.read()

    # Fetch all spaces if spaces were not configured via settings
    if len(settings.SPACES_TO_EXPORT) > 0:
        spaces_to_export = settings.SPACES_TO_EXPORT
    else:
        spaces_to_export = []
        page_url = '%s/wiki/api/v2/spaces?limit=25' % settings.CONFLUENCE_BASE_URL
        while page_url:
            response = utils.http_get(page_url, auth=settings.HTTP_AUTHENTICATION, headers=settings.HTTP_CUSTOM_HEADERS,
                                      verify_peer_certificate=settings.VERIFY_PEER_CERTIFICATE,
                                      proxies=settings.HTTP_PROXIES)
            for space in response['results']:
                spaces_to_export.append(space['id'])

            if 'next' in response['_links'].keys():
                page_url = response['_links']['next']
                page_url = '%s%s' % (settings.CONFLUENCE_BASE_URL, page_url)
            else:
                page_url = None

    print('Exporting %d space(s): %s\n' % (len(spaces_to_export), ', '.join(spaces_to_export)))

    # Export spaces
    space_counter = 0
    duplicate_space_names = {}
    space_matching = {}
    for space in spaces_to_export:
        space_counter += 1

        # Create folders for this space
        space_folder_name = provide_unique_file_name(duplicate_space_names, space_matching, space, is_folder=True)
        space_folder = '%s/%s' % (settings.EXPORT_FOLDER, space_folder_name)
        try:
            os.makedirs(space_folder)
            download_folder = '%s/%s' % (space_folder, settings.DOWNLOAD_SUB_FOLDER)
            os.makedirs(download_folder)

            print("Exporting this page %s" % space)
            space_url = '%s/wiki/api/v2/spaces/%s?expand=homepage' % (settings.CONFLUENCE_BASE_URL, space)
            response = utils.http_get(space_url, auth=settings.HTTP_AUTHENTICATION,
                                      headers=settings.HTTP_CUSTOM_HEADERS,
                                      verify_peer_certificate=settings.VERIFY_PEER_CERTIFICATE,
                                      proxies=settings.HTTP_PROXIES)
            space_name = response['name']

            print('SPACE (%d/%d): %s (%s)' % (space_counter, len(spaces_to_export), space_name, space))

            space_page_id = response['homepageId']

            path_collection = fetch_page_recursively(space_page_id, space_folder, download_folder, html_template)

            if path_collection:
                # Create index file for this space
                space_index_path = '%s/index.html' % space_folder
                space_index_title = 'Index of Space %s (%s)' % (space_name, space)
                space_index_content = create_html_index(path_collection)
                utils.write_html_2_file(space_index_path, space_index_title, space_index_content, html_template)
        except utils.ConfluenceException as e:
            error_print('ERROR: %s' % e)
        except OSError:
            print('WARNING: The space %s has been exported already. Maybe you mentioned it twice in the settings'
                  % space)

    # Finished output
    print_finished_output()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        error_print('ERROR: Keyboard Interrupt.')
        sys.exit(1)

