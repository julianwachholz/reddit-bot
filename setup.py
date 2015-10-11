# -*- coding: utf-8 -*-

from setuptools import setup

setup(
    name='reddit_bot',
    version='0.1.1',
    url='https://github.com/reddit-bots/reddit-bot',
    license='GPLv3',
    author='Julian Wachholz',
    author_email='julian@wachholz.ch',
    description='A clean Reddit bot script foundation.',
    long_description=open('README.rst').read(),
    keywords='reddit bot api',
    packages=['reddit_bot'],
    package_dir={'reddit_bot': 'reddit_bot'},
    package_data={'reddit_bot': ['*.template']},
    install_requires=['praw>=3.3.0'],
    entry_points={'console_scripts': [
        'run-reddit-bot = reddit_bot.main:run',
    ]},
    platforms='any',
    classifiers=[
        'Environment :: Web Environment',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: GNU General Public License (GPL)',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Topic :: Internet :: WWW/HTTP :: Dynamic Content',
        'Topic :: Software Development :: Libraries :: Python Modules',
        'Topic :: Utilities',
        'Programming Language :: Python',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3.3',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
    ]
)
