import logging

from datetime import datetime, timedelta

from .base import RedditBot


logger = logging.getLogger(__name__)


class RedditMessageBot(RedditBot):
    """
    A RedditBot that can occasionally check its private messages.

    """
    @classmethod
    def get_scope(cls):
        return super(RedditMessageBot, cls).get_scope() | {
            'privatemessages',
        }

    def bot_start(self):
        super(RedditMessageBot, self).bot_start()

        self.last_mail_check = None

    def loop(self, subreddit):
        super(RedditMessageBot, self).loop(subreddit)

        self.check_mail_if_necessary()

    def check_mail_if_necessary(self):
        delta = timedelta(seconds=self.settings['check_mail'])
        if self.last_mail_check is None:
            self.check_mail()
        elif self.last_mail_check + delta < datetime.now():
            self.check_mail()

    def check_mail(self):
        logger.info('check_mail')
        self.last_mail_check = datetime.now()

        if not self.r.get_me().has_mail:
            return

        self.before_mail_check()
        for message in self.r.get_unread(unset_has_mail=True):
            self.on_message(message)
        self.after_mail_check()

    def before_mail_check(self):
        pass

    def on_message(self, message):
        if message.author is None and message.subreddit:
            self.on_subreddit_message(message.subreddit.display_name, message)
        elif message.author is not None:
            if message.author.name in self.admins:
                self.on_admin_message(message)
            else:
                self.on_user_message(message.author.name, message)

    def on_subreddit_message(self, subreddit, message):
        logger.info('{}.on_subreddit_message is not implemented.'.format(self.__class__.__name__))

    def on_admin_message(self, message):
        logger.info('{}.on_admin_message is not implemented.'.format(self.__class__.__name__))

    def on_user_message(self, user, message):
        logger.info('{}.on_user_message is not implemented'.format(self.__class__.__name__))

    def after_mail_check(self):
        pass
