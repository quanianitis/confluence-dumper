# -*- coding: utf-8 -*-

"""
Confluence-dumper: A Python project to export only page IDs from Confluence.
"""

from __future__ import print_function
import sys
import codecs
import os
import utils
import settings


CONFLUENCE_DUMPER_VERSION = '1.1.0'
TITLE_OUTPUT = 'C O N F L U E N C E   D U M P E R  %s' % CONFLUENCE_DUMPER_VERSION


def error_print(*args, **kwargs):
    """ Wrapper for the print function which leads to stderr outputs. """
    print(*args, file=sys.stderr, **kwargs)


def fetch_page_ids_recursively(page_id, depth=0):
    """ Fetches Confluence page and its child pages, returning only page IDs.

    :param page_id: Confluence page id.
    :param depth: (optional) Hierarchy depth of the handled Confluence page.
    :returns: A list of page IDs.
    """
    try:
        page_url = '%s/wiki/rest/api/content/%s?expand=children.page' % (settings.CONFLUENCE_BASE_URL, page_id)
        response = utils.http_get(page_url, auth=settings.HTTP_AUTHENTICATION, headers=settings.HTTP_CUSTOM_HEADERS,
                                  verify_peer_certificate=settings.VERIFY_PEER_CERTIFICATE,
                                  proxies=settings.HTTP_PROXIES)

        page_title = response['title']
        print('%sPAGE: %s (%s)' % ('\t'*(depth+1), page_title, page_id))

        # Collect this page ID
        page_ids = [page_id]

        # Iterate through all child pages
        child_page_url = '%s/wiki/rest/api/content/%s/child/page?limit=25' % (settings.CONFLUENCE_BASE_URL, page_id)
        while child_page_url:
            response = utils.http_get(child_page_url, auth=settings.HTTP_AUTHENTICATION, 
                                      headers=settings.HTTP_CUSTOM_HEADERS, verify_peer_certificate=settings.VERIFY_PEER_CERTIFICATE,
                                      proxies=settings.HTTP_PROXIES)
            for child_page in response['results']:
                child_page_ids = fetch_page_ids_recursively(child_page['id'], depth=depth+1)
                page_ids.extend(child_page_ids)

            # Get the next set of child pages, if available
            if 'next' in response['_links'].keys():
                child_page_url = response['_links']['next']
                child_page_url = '%s%s' % (settings.CONFLUENCE_BASE_URL, child_page_url)
            else:
                child_page_url = None

        return page_ids

    except utils.ConfluenceException as e:
        error_print('%sERROR: %s' % ('\t'*(depth+1), e))
        return []


def main():
    """ Main function to start the confluence-dumper to fetch only page IDs. """
    
    print('\n\t %s' % TITLE_OUTPUT)
    print('\t %s\n' % ('='*len(TITLE_OUTPUT)))
    print('Fetching only page IDs from Confluence...\n')

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

    print('Fetching page IDs for %d space(s): %s\n' % (len(spaces_to_export), ', '.join(spaces_to_export)))

    # Fetch page IDs for all spaces
    for space in spaces_to_export:
        print("\nFetching pages for space: %s" % space)
        space_url = '%s/wiki/api/v2/spaces/%s?expand=homepage' % (settings.CONFLUENCE_BASE_URL, space)
        response = utils.http_get(space_url, auth=settings.HTTP_AUTHENTICATION, 
                                  headers=settings.HTTP_CUSTOM_HEADERS, verify_peer_certificate=settings.VERIFY_PEER_CERTIFICATE,
                                  proxies=settings.HTTP_PROXIES)

        space_page_id = response['homepageId']
        page_ids = fetch_page_ids_recursively(space_page_id)
        print("\nCollected page IDs: %s" % ', '.join(page_ids))

    print('\nFinished fetching page IDs!\n')


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        error_print('ERROR: Keyboard Interrupt.')
        sys.exit(1)

