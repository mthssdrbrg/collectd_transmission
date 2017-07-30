#!/usr/bin/env python
# -*- coding: utf-8 -*- vim:fileencoding=utf-8:
# vim: tabstop=4:shiftwidth=4:softtabstop=4:expandtab

'''
..  moduleauthor:: Alexandros Kosiaris
'''

import collectd
import transmissionrpc
import re
from distutils.version import StrictVersion

PLUGIN_NAME = 'transmission'

data = {}
metrics = {
    # General metrics
    'general': [
        'activeTorrentCount',
        'torrentCount',
        'downloadSpeed',
        'uploadSpeed',
        'pausedTorrentCount',
        'blocklist_size',
    ],
    # All time metrics
    'cumulative': [
        'downloadedBytes',
        'filesAdded',
        'uploadedBytes',
        'secondsActive',
        'sessionCount',
    ],
    # Per session (restart) metrics
    'current': [
        'downloadedBytes',
        'filesAdded',
        'uploadedBytes',
        'secondsActive',
        'sessionCount',
    ]
}


def config(config):
    '''
    Read the configuration and store it at a shared variable

    Retrieve the configuration from the config variable passed by collectd to
    the python module

    Args:
        config: The config instance passed by collectd to the module
    Returns:
        Nothing
    '''
    for child in config.children:
        data[child.key] = child.values[0]


def initialize():
    '''
    Collectd initialization routine
    '''
    username = data['username']
    password = data['password']
    address = data.get('address', 'http://localhost:9091/transmission/rpc')
    timeout = int(data.get('timeout', '5'))
    try:
        c = transmissionrpc.Client(address=address, user=username, password=password, timeout=timeout)
    except transmissionrpc.error.TransmissionError:
        c = None
    data['client'] = c


def shutdown():
    '''
    Collectd shutdown routive
    '''
    # Not really any resource to close, just clear the object
    data['client'] = None


def field_getter(stats, key, category):
    '''
    Get the statistics associated with a key and category

    Args:
        stats (dict): A dictionary containing the statistics
        key (str): A string to denote the name of the metric
        category (str): The category this metric belongs in. Possible values:
        'cumulative', 'current', 'general'

    Returns:
        int. The metric value or 0
    '''
    # 0.9 and onwards have statistics in a different field
    client_version = transmissionrpc.__version__
    if StrictVersion(client_version) >= StrictVersion('0.9'):
        if category == 'cumulative':
            return stats.cumulative_stats[key]
        elif category == 'current':
            return stats.current_stats[key]
        else:  # We are in "general"
            return getattr(stats, key)
    else:
        if category == 'cumulative':
            return stats.fields['cumulative_stats'][key]
        elif category == 'current':
            return stats.fields['current_stats'][key]
        else:  # We are in "general"
            return stats.fields[key]


def snake_case(s):
    return re.sub('([A-Z]+)', r'_\1', s).lower()


def get_stats():
    '''
    Collectd routine to actually get and dispatch the statistics
    '''
    # If we are not correctly initialized, initialize us once more.
    # Something happened after the first init and we have lost state
    if 'client' not in data or data['client'] is None:
        shutdown()
        initialize()
    # And let's fetch our data
    try:
        stats = data['client'].session_stats()
    except transmissionrpc.error.TransmissionError:
        shutdown()
        initialize()
        return  # On this run, just fail to return anything
    # Let's get our data
    for category, catmetrics in metrics.items():
        for metric in catmetrics:
            vl = collectd.Values(type='gauge',
                                 plugin=PLUGIN_NAME,
                                 type_instance='%s.%s' % (category, snake_case(metric)))
            vl.dispatch(values=[field_getter(stats, metric, category)])

    announce_stats = get_announce_stats()
    for name, val in announce_stats.items():
        vl = collectd.Values(type='gauge',
                             plugin=PLUGIN_NAME,
                             type_instance='announce.%s' % (name))
        vl.dispatch(values=[val])


def get_announce_stats():
    result = {'succeeded': 0, 'failed': 0}
    torrents = data['client'].get_torrents()
    for torrent in torrents:
        tracker_stats = getattr(torrent, 'trackerStats')[0]
        if tracker_stats['lastAnnounceSucceeded']:
            result['succeeded'] += 1
        else:
            result['failed'] += 1
    return result


# Register our functions
collectd.register_config(config)
collectd.register_init(initialize)
collectd.register_read(get_stats)
collectd.register_shutdown(shutdown)
