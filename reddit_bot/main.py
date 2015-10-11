#!/usr/bin/env python
# -*- encoding: utf-8 -*-
from __future__ import unicode_literals, print_function

import logging
import json
import sys
import os
from importlib import import_module

from praw import Reddit


logger = logging.getLogger(__name__)

LOG_FORMAT = '%(asctime)-15s %(levelname)-6s %(name)-15.15s %(message)s'
CONFIG_TEMPLATE = 'config.json.template'


def get_bot_class(import_path):
    import_parts = import_path.split('.')
    klass = import_parts[-1]
    module_name = '.'.join(import_parts[:-1])

    try:
        module = import_module(module_name)
        return getattr(module, klass)
    except ValueError:
        print('Please supply an import path.')
    except ImportError:
        print('Could not import module "{}"!'.format(module_name))
    except AttributeError:
        print('Could not find class "{}" in "{}"!'.format(klass, module_name))
    return None


def _ask_config(config, in_settings=False):
    for key, default in config.items():
        if key == 'settings':
            _ask_config(default, in_settings=True)
        elif key == 'bot_class':
            while True:
                value = raw_input("Import path for bot class: ")
                if get_bot_class(value) is not None:
                    break
            config[key] = value
        elif isinstance(default, dict):
            _ask_config(default)
        elif in_settings or default.startswith('{') and default.endswith('}'):
            val_type = type(default)

            if isinstance(default, type('str')):
                default = default.strip('{}')

            if isinstance(default, type('str')) and default.isupper():
                while True:
                    value = raw_input("{}: ".format(key))
                    if value:
                        config[key] = value or default
                        break
                    else:
                        print("{} is required!".format(key))
            else:
                while True:
                    try:
                        value = raw_input("{} ({}): ".format(key, default))
                        if value:
                            value = val_type(value)
                        elif in_settings:
                            config.pop(key, None)
                            break
                    except ValueError as e:
                        print(e)
                    else:
                        config[key] = value or default
                        break


def make_config(filename):
    """
    Make a new config file.

    """
    here = os.path.dirname(os.path.abspath(__file__))
    template_file = os.path.join(here, CONFIG_TEMPLATE)

    with open(template_file, 'r') as f:
        config = json.load(f)

    print('Generating a new config, press [Enter] to accept default value.')
    _ask_config(config)

    bot_class = get_bot_class(config['bot_class'])

    r = Reddit('praw/oauth_access_info_setup 1.0')
    r.set_oauth_app_info(**config['oauth_info'])

    url = r.get_authorize_url('uniqueKey', bot_class.get_scope(), True)
    print('Go to this url: =====\n\n{}\n\n====='.format(url))
    code = raw_input('and enter the authorization code: ')
    assert code, "No authorization code supplied."
    access_info = r.get_access_information(code)
    access_info.pop('scope', None)
    config['access_info'] = access_info

    with open(filename, 'w') as f:
        json.dump(config, f, indent=2)

    print('Wrote config {!r}!'.format(filename))
    return config


def main(config_file):
    try:
        with open(sys.argv[1]) as config_file:
            logger.debug('loaded config from {}'.format(sys.argv[1]))
            config = json.load(config_file)
    except IOError:
        config = make_config(sys.argv[1])

    logging.basicConfig(level=config.get('loglevel', 'WARN'), format=LOG_FORMAT)

    if not os.path.exists(config['subreddit_list']):
        open(config['subreddit_list'], 'a').close()
        logger.info("Created empty {}".format(config['subreddit_list']))

    if not os.path.exists(config['blocked_users']):
        open(config['blocked_users'], 'a').close()
        logger.info("Created empty {}".format(config['blocked_users']))

    bot_class = get_bot_class(config['bot_class'])
    bot = bot_class(config)

    try:
        bot.run_forever()
    except KeyboardInterrupt:
        print('Goodbye!')


def run():
    if len(sys.argv) != 2:
        sys.stderr.write('Usage: {} <config_file>\n'.format(sys.argv[0]))
        sys.stderr.write('Will create <config_file> if it does not exist.\n')
        sys.exit(1)

    run_path = os.getcwd()
    if run_path not in sys.path:
        sys.path.append(run_path)

    main(sys.argv[1])
