# -*- encoding: utf-8 -*-
from __future__ import unicode_literals

import sys
import logging
import time

from itertools import cycle

from praw import Reddit
from praw.errors import Forbidden, RateLimitExceeded, HTTPException
from requests.exceptions import ConnectionError


logger = logging.getLogger(__name__)


DEFAULT_SETTINGS = {
    'loop_sleep': 2,
    'check_mail': 60,
    'fetch_limit': 50,
    'comment_max_age': 900,
    'min_comment_score': 1,
    'reply_if_score_hidden': False,
    'check_parent_comments': True,
    'score_check_depth': 4,
    'max_replies_per_post': 3,
    'subreddit_timeout': 1800,
    'wait_after_reply': 60,
}


class _RedditBotBase(object):
    """
    Base API methods for a Reddit bot.

    """
    @classmethod
    def get_scope(cls):
        """Get the required OAuth scope for this bot."""
        return set()

    def bot_start(self):
        """Bot is logged in and is starting event loop."""
        pass

    def bot_stop(self):
        """Called before the bot shuts down normally."""
        pass

    def bot_error(self, exception):
        """Bot got an unexpected exception."""
        # TODO print stacktrace and context variables
        sys.stderr.write('{!r}'.format(exception))

    def loop(self, subreddit):
        """Looping over this subreddit now.

        :type subreddit: str
        :param subreddit: The name of the subreddit (without /r/)
        """
        pass


class RedditBot(_RedditBotBase):
    """
    Basic extendable Reddit bot.

    Provides means to loop over a list of whitelisted subreddits.

    """
    VERSION = (0, 0, 0)  # override this
    USER_AGENT = '{name} v{version} (by /u/{admin})'

    # if loop() returns this the bot will refresh its settings
    BOT_SHOULD_REFRESH = 'BOT_SHOULD_REFRESH'

    def __init__(self, config):
        """
        Initialize the bot with a dict of configuration values.

        """
        self._setup(config)
        self._login(config)

    def _setup(self, config):
        try:
            self.bot_name = config['bot_name']
            self.admin_name = config['admin_name']

            self.settings = DEFAULT_SETTINGS.copy()
            self.settings.update(config.get('settings', {}))

            self.subreddits = self._get_subreddits(config['subreddit_list'])
            self.blocked_users = self._get_blocked_users(config['blocked_users'])
        except KeyError as e:
            import sys
            sys.stderr.write('error: missing {} in configuration'.format(e))
            sys.exit(2)

    def _login(self, config):
        logger.info('Attempting to login using OAuth2')

        for attr in ['client_id', 'client_secret', 'redirect_uri']:
            assert attr in config['oauth_info'], 'Missing `{}` in oauth_info'.format(attr)

        user_agent = self.USER_AGENT.format(
            name=self.bot_name,
            admin=self.admin_name,
            version='.'.join(map(str, self.VERSION))
        )
        self.r = Reddit(user_agent)
        self.r.set_oauth_app_info(**config['oauth_info'])

        for attr in ['access_token', 'refresh_token']:
            assert attr in config['access_info'], 'Missing `{}` in access_info'.format(attr)
        access_info = config['access_info']
        access_info['scope'] = self.__class__.get_scope()
        self.r.set_access_credentials(**access_info)

        logger.info('Logged in as {}'.format(self.r.user.name))

    @classmethod
    def get_scope(cls):
        """Basic permission scope for RedditReplyBot operations."""
        return super(RedditBot, cls).get_scope() | {
            'identity',
        }

    def run_forever(self):
        self.bot_start()
        try:
            while True:
                self.do_loop()
                self.refresh()
        except Exception as e:
            self.bot_error(e)
            raise
        finally:
            self.bot_stop()

    def refresh(self):
        logger.info('Refreshing settings')
        self.subreddits = self._get_subreddits()
        self.blocked_users = self._get_blocked_users()

    def do_loop(self):
        for subreddit in cycle(self.subreddits):
            try:
                if self.loop(subreddit) == self.BOT_SHOULD_REFRESH:
                    break
            except Forbidden as e:
                logger.error('Forbidden in {}! Removing from whitelist.'.format(subreddit))
                self.remove_subreddits(subreddit)
                break
            except RateLimitExceeded as e:
                logger.warn('RateLimitExceeded! Sleeping {} seconds.'.format(e.sleep_time))
                time.sleep(e.sleep_time)
            except (ConnectionError, HTTPException) as e:
                logger.warn('Error: Reddit down or no connection? {!r}'.format(e))
                time.sleep(self.settings['loop_sleep'] * 10)
            else:
                time.sleep(self.settings['loop_sleep'])
        else:
            logger.error("No subreddits in file. Will read file again in 5 seconds.")
            time.sleep(5)

    def _get_file_lines(self, filename):
        with open(filename) as f:
            file_lines = set(map(str.strip, f.readlines()))
        return file_lines

    def _set_file_lines(self, filename, lines):
        with open(filename, 'w') as f:
            f.write('\n'.join(lines))

    def _get_subreddits(self, filename=None):
        if isinstance(filename, list):
            return filename

        if filename is not None:
            self.subreddits_file = filename
        subreddits = self._get_file_lines(self.subreddits_file)

        logger.info('Subreddits: {} entries'.format(len(subreddits)))
        return subreddits

    def _set_subreddits(self):
        if self.subreddits_file is None:
            raise RuntimeError('no subreddits file defined')
        self._set_file_lines(self.subreddits_file, self.subreddits)

    def _get_blocked_users(self, filename=None):
        if filename is not None:
            self.blocked_users_file = filename
        blocked_users = self._get_file_lines(self.blocked_users_file)

        logger.info('Blocked users: {} entries'.format(len(blocked_users)))
        return blocked_users

    def _set_blocked_users(self):
        if self.blocked_users_file is None:
            raise RuntimeError('no blocked_users file defined')
        self._set_file_lines(self.blocked_users_file, self.blocked_users)

    def is_user_blocked(self, user_name):
        if user_name == self.bot_name:
            return True
        return user_name in self.blocked_users

    def is_subreddit_whitelisted(self, subreddit):
        return subreddit in self.subreddits

    def remove_subreddits(self, *subreddits):
        for subreddit in subreddits:
            if subreddit in self.subreddits:
                self.subreddits.remove(subreddit)
        self._set_subreddits()

    def add_subreddits(self, *subreddits):
        for subreddit in subreddits:
            if subreddit not in self.subreddits:
                self.subreddits.add(subreddit)
        self._set_subreddits()

    def block_users(self, *users):
        for user in users:
            if user not in self.blocked_users:
                self.blocked_users.add(user)
        self._set_blocked_users()

    def unblock_users(self, *users):
        for user in users:
            if user in self.blocked_users:
                self.blocked_users.remove(user)
        self._set_blocked_users()
