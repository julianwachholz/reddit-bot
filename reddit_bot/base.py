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

        self.subreddits = self._get_subreddits()
        self.blocked_users = self._get_blocked_users()

    def _setup(self, config):
        try:
            admins = config['admins']
            if isinstance(admins, list):
                self.admins = admins
            else:
                self.admins = list(map(str.strip, admins.split(',')))

            self.settings = DEFAULT_SETTINGS.copy()
            self.settings.update(config.get('settings', {}))
        except KeyError as e:
            import sys
            sys.stderr.write('error: missing {} in configuration'.format(e))
            sys.exit(2)

    def _login(self, config):
        logger.info('Attempting to login using OAuth2')

        for attr in ['client_id', 'client_secret', 'redirect_uri']:
            assert attr in config['oauth_info'], 'Missing `{}` in oauth_info'.format(attr)

        self.r = Reddit('OAuth Login v1.0')
        self.r.set_oauth_app_info(**config['oauth_info'])

        for attr in ['access_token', 'refresh_token']:
            assert attr in config['access_info'], 'Missing `{}` in access_info'.format(attr)
        access_info = config['access_info']
        access_info['scope'] = self.__class__.get_scope()
        self.r.set_access_credentials(**access_info)
        self.bot_name = self.r.user.name
        self.admins.append(self.bot_name)
        user_agent = self.USER_AGENT.format(
            name=self.bot_name,
            admin=self.admins[0],
            version='.'.join(map(str, self.VERSION))
        )
        logger.debug('User-Agent: {!r}'.format(user_agent))
        self.r.http.headers['User-Agent'] = user_agent
        logger.info('Logged in as {}'.format(self.bot_name))

    @classmethod
    def get_scope(cls):
        """Basic permission scope for RedditReplyBot operations."""
        return super(RedditBot, cls).get_scope() | {
            'identity',
            'subscribe',
            'mysubreddits',
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
                logger.warning('RateLimitExceeded! Sleeping {} seconds.'.format(e.sleep_time))
                time.sleep(e.sleep_time)
            except (ConnectionError, HTTPException) as e:
                logger.warning('Error: Reddit down or no connection? {!r}'.format(e))
                time.sleep(self.settings['loop_sleep'] * 10)
            else:
                time.sleep(self.settings['loop_sleep'])
        else:
            logger.error("No subreddits in file. Will read file again in 5 seconds.")
            time.sleep(5)

    def _get_subreddits(self):
        subreddits = list(map(lambda s: s.display_name, self.r.get_my_subreddits()))
        logger.info('Subreddits: {} entries'.format(len(subreddits)))
        logger.debug('List: {!r}'.format(subreddits))
        return subreddits

    def _get_blocked_users(self, filename=None):
        """Friends are blocked users, because Reddit only allows blocking
        users by private messages."""
        blocked_users = list(map(lambda u: u.name, self.r.get_friends()))
        logger.info('Blocked users: {} entries'.format(len(blocked_users)))
        logger.debug('List: {!r}'.format(blocked_users))
        return blocked_users

    def is_user_blocked(self, user_name):
        if user_name == self.bot_name:
            return True
        return user_name in self.blocked_users

    def is_subreddit_whitelisted(self, subreddit):
        return subreddit in self.subreddits

    def remove_subreddits(self, *subreddits):
        for sub_name in subreddits:
            if sub_name in self.subreddits:
                self.subreddits.remove(sub_name)
                sub = self.r.get_subreddit(sub_name)
                sub.unsubscribe()
                logger.info('Unsubscribed from /r/{}'.format(sub_name))

    def add_subreddits(self, *subreddits):
        for sub_name in subreddits:
            if sub_name not in self.subreddits:
                self.subreddits.add(sub_name)
                sub = self.r.get_subreddit(sub_name)
                sub.subscribe()
                logger.info('Subscribed to /r/{}'.format(sub_name))

    def block_users(self, *users):
        for user_name in users:
            if user_name not in self.blocked_users:
                self.blocked_users.add(user_name)
                user = self.r.get_redditor(user_name)
                user.friend()
                logger.info('Blocked /u/{}'.format(user_name))

    def unblock_users(self, *users):
        for user_name in users:
            if user_name in self.blocked_users:
                self.blocked_users.remove(user_name)
                user = self.r.get_redditor(user_name)
                user.unfriend()
                logger.info('Unblocked /u/{}'.format(user_name))
