import logging

from collections import Counter
from datetime import datetime, timedelta

from .base import RedditBot


logger = logging.getLogger(__name__)


class _RedditReplyBotMixin(object):
    """
    Keep track of how often we post in a subreddit.

    """
    @classmethod
    def get_scope(cls):
        return super(_RedditReplyBotMixin, cls).get_scope() | {
            'read',
            'submit',
            'edit',
        }

    def bot_start(self):
        super(_RedditReplyBotMixin, self).bot_start()
        self.subreddit_timeouts = {}

    def _check_things(self, thing_type, subreddit, before=None):
        """
        Fetch latest things in a subreddit.

        :param 'comments'|'submissions' thing_type: what things to fetch
        :param str subreddit: name of the subreddit to check
        :param str|None before: latest thing id

        """
        logger.debug('_check_things(subreddit={!r}, before={!r})'.format(
            subreddit, before))

        params = {'sort': 'old', 'before': before}
        latest_created = 0
        latest_fullname = before

        if thing_type == 'submissions':
            things = self.r.get_subreddit(subreddit).get_new(
                limit=self.settings['fetch_limit'],
                params=params
            )
        elif thing_type == 'comments':
            things = self.r.get_comments(
                subreddit,
                limit=self.settings['fetch_limit'],
                params=params
            )

        for thing in things:
            if thing.created_utc > latest_created:
                latest_created = thing.created_utc
                latest_fullname = thing.fullname
            yield 'thing', thing
        # remember newest comment so we dont fetch it again
        yield 'end', latest_fullname

    def can_post_in_subreddit(self, subreddit):
        """Check if we should post again in this subreddit."""
        if subreddit not in self.subreddit_timeouts \
           or self.subreddit_timeouts[subreddit] < datetime.now():
            return True
        return False

    def did_post_in_subreddit(self, subreddit):
        now = datetime.now()
        delta = timedelta(seconds=self.settings['subreddit_timeout'])
        self.subreddit_timeouts[subreddit] = now + delta


class RedditCommentBot(_RedditReplyBotMixin, RedditBot):
    """
    A bot capable of replying to comments.

    """
    def bot_start(self):
        super(RedditCommentBot, self).bot_start()

        # TODO occasionally check size of this (with sys.getsizeof?) and clear
        self.submissions_comment_counter = Counter()
        self.subreddit_fullnames = {}
        self.comment_checks = self.get_comment_checks()

        if self.settings['check_parent_comments']:
            self.comment_checks.append(self.comment_has_good_parents)

    def get_comment_checks(self):
        # TODO check score of actual submission
        # TODO do not reply to moderator comments
        return [
            self.comment_is_new,
            self.comment_submission_cap_not_reached,
            self.comment_author_not_blacklisted,
        ]

    def reply_comment(self, comment):
        """
        Implement the `reply_comment` method to reply to comments
        that meet the criteria as specified by the list of functions
        returned by `get_comment_checks`.

        You should return True if a reply was made to the comment.

        """
        raise NotImplementedError('Implement {}.reply_comment(comment)'.format(
                                  self.__class__.__name__))

    def loop(self, subreddit):
        super(RedditCommentBot, self).loop(subreddit)

        if not self.can_post_in_subreddit(subreddit):
            return
        latest = self.subreddit_fullnames.get(subreddit, None)
        self.check_comments(subreddit, before=latest)

    def check_comments(self, subreddit, before=None):
        """Fetch latest comments in a subreddit."""
        for control, thing in self._check_things('comments', subreddit, before):
            if control == 'end':
                self.subreddit_fullnames[subreddit] = thing
                break

            comment = thing

            if self.is_valid_comment(comment):
                did_reply = self.reply_comment(comment)
                if did_reply:
                    logger.info('replied to comment {}'.format(comment.id))
                    self.submissions_comment_counter[comment.link_id] += 1
                    self.did_post_in_subreddit(subreddit)
                    self.subreddit_fullnames[subreddit] = comment.fullname
                    break

    def is_valid_comment(self, comment):
        """Check if the comment is eligible for a reply."""
        return all(check(comment) for check in self.comment_checks)

    def comment_is_new(self, comment):
        """Only reply to new comments."""
        now = datetime.utcnow()
        created = datetime.utcfromtimestamp(comment.created_utc)
        delta = timedelta(seconds=self.settings['comment_max_age'])

        return created + delta > now

    def comment_submission_cap_not_reached(self, comment):
        max_replies = self.settings['max_replies_per_post']

        return self.submissions_comment_counter[comment.link_id] < max_replies

    def comment_author_blacklisted(self, comment):
        if not comment.author:
            return True

        return self.is_user_blocked(comment.author.name)

    def comment_author_not_blacklisted(self, comment):
        return not self.comment_author_blacklisted(comment)

    def comment_has_good_parents(self, comment, depth=0):
        """Check the score and user of parent comments."""
        logger.debug('comment_has_good_parents('
                     'comment={!r}, depth={!r})'.format(comment.id, depth))
        return not any(self._comment_has_good_parents(comment, depth))

    def _comment_has_good_parents(self, comment, depth):
        yield self.comment_author_blacklisted(comment)
        yield comment.score_hidden and not self.settings['reply_if_score_hidden']
        yield comment.score < self.settings['min_comment_score']
        if comment.is_root or depth > self.settings['score_check_depth']:
            return
        yield not self.comment_has_good_parents(
            self._comment_parent(comment), depth + 1)

    def _comment_parent(self, comment):
        return self.r.get_info(thing_id=comment.parent_id)


class RedditSubmissionBot(_RedditReplyBotMixin, RedditBot):
    """
    A bot capable of replying to submissions.

    """
    def bot_start(self):
        super(RedditSubmissionBot, self).bot_start()

        self.subreddit_submissions = {}

    def is_valid_submission(self, submission):
        """Overwrite with your checks."""
        return True

    def reply_submission(self, submission):
        """
        Implement the `reply_submission` method to post a top level
        comment to subreddit posts.

        You should return True if a reply was made.

        """
        raise NotImplementedError('Implement {}.reply_submission(submission)'.format(
                                  self.__class__.__name__))

    def loop(self, subreddit):
        super(RedditSubmissionBot, self).loop(subreddit)

        if not self.can_post_in_subreddit(subreddit):
            return

        latest = self.subreddit_submissions.get(subreddit, None)
        self.check_submissions(subreddit, before=latest)

    def check_submissions(self, subreddit, before=None):
        """Fetch latest submissions in a subreddit."""
        for control, thing in self._check_things('submissions', subreddit, before):
            if control == 'end':
                self.subreddit_submissions[subreddit] = thing
                break

            submission = thing

            if self.is_valid_submission(submission):
                did_reply = self.reply_submission(submission)
                if did_reply:
                    logger.info('replied to submission: {}'.format(submission.id))
                    self.did_post_in_subreddit(subreddit)
                    self.subreddit_submissions[subreddit] = submission.fullname
                    break

