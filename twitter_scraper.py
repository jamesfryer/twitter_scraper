#! /usr/bin/python
# $Id$
# Scrape Twitter and convert to Atom
# 2013-06-13
# Public domain

"""This script scrapes a Twitter HTML page and converts it to Atom or RSS.

You can run it from the command line, as a CGI script or as WSGI (with 
WSGIApplicationGroup %{GLOBAL}).

On the command line you can use a Twitter username or -s and a search string.

I've tried to use as few external libraries as possible. It requires 
BeautifulSoup 4 and PyRSS2Gen (if you want RSS).

I'm releasing this into the public domain, do what you like with it, but 
if you want to make a contribution you can send bitcoins to 
1rLaVLyzXLP46VbQnMHNFg6S8KqrcNZZN.

This meets my needs but has not been thoroughly tested, please contact me 
if you find any bugs. The RSS in particular needs more testing.

There is also JSON output, this is just for test purposes really, it bears no 
relation to any JSON feed generated by Twitter.

James Fryer <jim@invocrown.com>
"""

import os
import sys
import argparse
from time import gmtime, strftime
from datetime import datetime
import logging
import json
from StringIO import StringIO
from urllib2 import urlopen, URLError
from urllib import quote
from urlparse import urlparse, urljoin
from cgi import parse_qs, escape
from bs4 import BeautifulSoup
try:
    import PyRSS2Gen as RSS2
except ImportError:
    RSS2 = None

TWITTER_BASE_URI = 'https://twitter.com/'
TWITTER_SEARCH_URI = TWITTER_BASE_URI + 'search/realtime?q='
CONTENT_TYPES = {
    'atom': 'application/atom+xml',
    'rss': 'application/rss+xml,',
    'json': 'application/json',
    }

class Main(object):
    output = ''
    def __call__(self, args=None):
        self.args = self.parse_args(args)
        if self.args.test:
            sys.argv = sys.argv[1:]
            unittest.main()
        else:
            if self.args.twitter_param is None:
                title = "Untitled feed"
                uri = None
            elif self.args.search:
                title = "Twitter search: %s" % self.args.twitter_param
                uri = uri_search(self.args.twitter_param)
            else:
                if self.args.twitter_param[0] == '@':
                    self.args.twitter_param = self.args.twitter_param[1:]
                title = "Twitter feed for: @%s" % self.args.twitter_param
                uri = uri_user(self.args.twitter_param)
            html = fetch(uri)
            tweets = scrape_tweets(html)
            if self.args.format == 'json':
                self.output = self.to_json(tweets)
            elif self.args.format == 'rss':
                if RSS2 is None:
                    self.output = "Sorry, PyRSS2Gen not installed, RSS output is not available."
                else:
                    self.output = self.to_rss(tweets, title, uri)
            else:
                self.output = self.to_atom(tweets, title, uri)
            if not self.args.quiet:
                print self.output
        
    def parse_args(self, args=None):
        parser = argparse.ArgumentParser(description="Twitter Scraper")
        parser.add_argument('twitter_param', nargs='?', help='Twitter username or search string')
        parser.add_argument('--search', '-s', action='store_true', help='Search twitter for string')
        parser.add_argument('--atom', '-a', dest='format', action='store_const', const='atom', help='Output Atom (default)')
        parser.add_argument('--rss', '-r', dest='format', action='store_const', const='rss', help='Output RSS')
        parser.add_argument('--json', '-j', dest='format', action='store_const', const='json', help='Output JSON (for test purposes)')
        parser.add_argument('--pretty-print', '-p', action='store_true', default=sys.stdout.isatty(), help="Format output for readability (JSON only at present)")
        parser.add_argument('--quiet', '-q', action='store_true', help="Don't print output")
        parser.add_argument('--test', '-t', action='store_true', help='Run tests')
        args = parser.parse_args(args)
        return args

    def to_json(self, tweets):
        indent = 4 if self.args.pretty_print else None
        return json.dumps(tweets, indent=indent, sort_keys=self.args.pretty_print)

    def to_atom(self, tweets, title, uri):
        feed_template = """<feed xmlns="http://www.w3.org/2005/Atom"> 
                {header}
                {entries}
            </feed>
            """
        entry_template = """<entry>
                    <id>{id}</id>
                    <title>{title}</title>
                    <link rel="alternate" href="{website}"/>
                    <link rel="icon" href="{icon}"/>
                    <content type="html">{body}</content>
                    <updated>{date}</updated>
                    <author><name>{user_name}</name><uri>{user_uri}</uri></author>
                </entry>
                """
        header = '<title>{title}</title><updated>{updated}</updated>'.format(title=title , updated=strftime('%Y-%m-%dT%H:%M:%SZ'))
        if uri is not None:
            header += '<id>{website}</id><link rel="alternate" href="{website}"/>'.format(website=uri)
        entries = []
        for tw in tweets:
            tmp = {}
            tmp['id'] = tmp['website'] = tw['uri']
            tmp['title'] = escape(tw['text']).encode('utf-8')
            tmp['body'] = escape(tw['html'])
            tmp['user_name'] = escape(tw['user_name']).encode('utf-8')
            tmp['user_uri'] = tw['user_uri']
            tmp['date'] = tw['date']
            tmp['icon'] = tw['icon']
            try:
                entries.append(entry_template.format(**tmp))
            except:
                logging.exception("Couldn't convert this tweet: %s" % tw)
        feed = feed_template.format(header=header, entries=''.join(entries))
        return feed

    def to_rss(self, tweets, title, uri):
        items = []
        for tw in tweets:
            items.append(RSS2.RSSItem(title=tw['text'], 
                    link=tw['uri'],
                    description=tw['html'],
                    pubDate=datetime.fromtimestamp(tw['time_t'])))
        rss2 = RSS2.RSS2(title=title, link=uri, items=items, description=title)
        file = StringIO()
        rss2.write_xml(file)
        return file.getvalue();

main = Main()

def application(environ, start_response):
    """WSGI app
        No args => HTML form
        user=twitter ID => user feed
        q=query => query
        format=atom|json|rss => format (default atom)
        
    Note there is an issue with BeautifulSoup under mod_wsgi. See:
        https://bugs.launchpad.net/beautifulsoup/+bug/948577
        https://techknowhow.library.emory.edu/blogs/branker/2010/07/30/django-lxml-wsgi-and-python-sub-interpreter-magic
    You need this, or use CGI:
        WSGIApplicationGroup %{GLOBAL}
        
    """
    vars = parse_qs(environ['QUERY_STRING'])
    def get_var(name, default=''):
        try:
            result = vars.get(name, [default])[0]
            result = escape(result)
            return result
        except AttributeError:
            return None
    # Get query args
    user = get_var('user')
    query = get_var('q')
    format = get_var('format', 'atom')
    # Show user feed
    if user != '':
        main(['--quiet', '--%s' % format, user])
        content = main.output
        content_type = CONTENT_TYPES[format]
    # Show search results
    elif query != '':
        main(['--quiet', '--search', '--%s' % format, query])
        content = main.output
        content_type = CONTENT_TYPES[format]
    # Show home page
    else:
        content = html_home()
        content_type = 'text/html'
    start_response('200 OK', [('Content-type', content_type)])
    return [content]

def uri_user(username):
    return TWITTER_BASE_URI + username
    
def uri_search(query):
    return TWITTER_SEARCH_URI + quote(query)
    
def fetch(uri_or_filename):
    if uri_or_filename is None:
        f = sys.stdin
    else:
        f = urlopen(uri_or_filename)
    return f.read()
    
def scrape_tweets(html):
    """
        From the HTML produced by twitter, return an array of dicts with the following fields:
            uri: URI of this tweet
            user_id: User ID from Twitter URI
            user_uri: Full URI of user
            user_name: Display name of user
            icon: User image
            html: HTML string of tweet
            text: Text string of tweet
            date: Date/time in ISO format
            time_t: Date/time in Unixtime (seconds since 1970)
    """
    def get_tweet(soup):
        def fix_uri(uri):
            u = urlparse(uri)
            return urljoin(TWITTER_BASE_URI, uri) if u.scheme == '' else uri
        def fix_content(content):
            # Fix relative URIs
            for tag in content.find_all('a'):
                tag['href'] = fix_uri(tag['href'])
            # Strip some annoying tags
            for tag in content.find_all('span', class_='invisible') + content.find_all('span', class_='js-display-url') + content.find_all('span', class_='tco-ellipsis'):
                tag.unwrap()
            for tag in content.find_all('s'):
                if tag.text in ('#', '@'):
                    next = tag.find_next()
                    tag.unwrap()
                    if next is not None:
                        next.unwrap()
            return content
        tweet = {}
        tweet['uri'] = uri_user(soup.select('a.details')[0]['href'][1:])
        tweet['user_id'] = soup.select('span.username')[0].b.text
        tweet['user_uri'] = uri_user(tweet['user_id'])
        tweet['user_name'] = soup.select('.fullname')[0].text.strip()
        tweet['icon'] = soup.select('img.avatar')[0]['src']
        content = fix_content(soup.select('p.tweet-text')[0])
        tweet['html'] = str(content)
        tweet['text'] = content.text
        tweet['time_t'] = int(soup.select('span._timestamp')[0]['data-time'])
        tweet['date'] = strftime('%Y-%m-%dT%H:%M:%SZ', gmtime(tweet['time_t']))
        return tweet
    result = []
    for soup in BeautifulSoup(html).find_all('div', class_='content'):
        try:
            result.append(get_tweet(soup))
        except (AttributeError, IndexError):
            pass
    return result
    
def html_home():
    script = """function show_hide(id, show)
    {
    if (document.getElementById)
        {
        obj = document.getElementById(id);
        if (typeof(show) == 'undefined')
            show = obj.style.display == "none";
        if (show)
            obj.style.display = "";
        else
            obj.style.display = "none";
        }
    }
"""
    return """<html>
<head>
<title>Scrape some tweets</title>
</head>
<body>
<h1>Twitter Scraper</h1>
<form method="get">
<strong>See a user's tweets:</strong>
<input type="text" name="user"><br>
<strong>Or, search Twitter:</strong>
<input type="text" name="q"><br>
<b>Format:</b>
<select name="format">
   <option value="atom">Atom</option>
   <option value="rss">RSS2</option>
   <option value="json">JSON</option>
</select><br>
<input type="submit">
</form>
<script type="text/javascript">
{js}
</script>
<p><a href="#" onclick="show_hide('docs')">About</a></p>
<div id='docs' style="display:none">
<pre>
{docs}
</pre>
</div>
</body>
</html>
""".format(docs=escape(__doc__), js=script)

    
# Tests
import unittest

class TestScrapeTweets(unittest.TestCase):
    test_html = """<html><body>
  <div class="content"> this is not a tweet so should be ignored
    <div class="stream-item-header">
      <a class="account-group js-user-profile-link" href="/artistsmakers">
        <img class="avatar js-action-profile-avatar " src="https://si0.twimg.com/profile_images/1362322919/danbyjan_normal.jpg" alt="Dan Thompson" data-user-id="15834810"/>
        <strong class="fullname js-action-profile-name">Dan Thompson</strong>
        <span>&rlm;</span>
          <span class="username js-action-profile-name">@artistsmakers</span>
      </a>
    </div>
      <p class="bio ">
          Placeshaker 
      </p>
  </div>

                <div class="content">
                        <a class="details with-icn js-details" href="/foo/status/123">foo</a>
                      <div class="stream-item-header">
                        <a class="account-group js-account-group js-action-profile js-user-profile-link js-nav"
                            href="/MerryMeats" data-user-id="508512780">
                        <img class="avatar js-action-profile-avatar" src="https://example.com/normal.png"
                                alt="MERRY MEATS YAPTON"> <strong class=
                        "fullname js-action-profile-name show-popup-with-id">
                        MERRY MEATS YAPTON</strong>
                        <span>&#8207;</span><span class=
                        "username js-action-profile-name"><s>@</s><b>MerryMeats</b></span></a>
                        <small class="time"><a href=
                        "/MerryMeats/status/345078080127258625"
                        class="tweet-timestamp js-permalink js-nav"
                        title="12:20 AM - 13 Jun 13"><span class=
                        "_timestamp js-short-timestamp js-relative-timestamp"
                        data-time="1371108000" data-long-form=
                        "true">41m</span></a></small>
                      </div>
                      <p class="js-tweet-text tweet-text"><span class="invisible removed"><s>Off</s></span> <a href="/expanded"><span class="tco-ellipsis removed">to</span></a> Worthing, <a href="http://example.com/notchanged">Petworth</a>, Bognor, <strong>Littlehampton</strong> and <span class="js-display-url">Chichester</span>! <s>#</s><b>hash</b> <s>@</s><b>at</b></p>
                    </div>
                    """
                    
    def test_scrape_tweets(self):
        tweets = scrape_tweets(self.test_html)
        self.assertEqual(1, len(tweets))
        tweet = tweets[0]
        self.assertEqual('https://twitter.com/foo/status/123', tweet['uri'])
        self.assertEqual('MerryMeats', tweet['user_id'])
        self.assertEqual('MERRY MEATS YAPTON', tweet['user_name'])
        self.assertEqual('https://twitter.com/MerryMeats', tweet['user_uri'])
        self.assertEqual('https://example.com/normal.png', tweet['icon'])
        self.assertEqual('<p class="js-tweet-text tweet-text"><s>Off</s> <a href="https://twitter.com/expanded">to</a> Worthing, <a href="http://example.com/notchanged">Petworth</a>, Bognor, <strong>Littlehampton</strong> and Chichester! #hash @at</p>', tweet['html'])
        self.assertEqual('Off to Worthing, Petworth, Bognor, Littlehampton and Chichester! #hash @at', tweet['text'])
        self.assertEqual('2013-06-13T07:20:00Z', tweet['date'])
            
if __name__ == '__main__':
    from wsgiref.handlers import CGIHandler
    if os.environ.get('GATEWAY_INTERFACE') is not None:
        CGIHandler().run(application)
    else:        
        main()
