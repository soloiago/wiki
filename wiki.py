import cgi
import os
import re
import random
import hashlib
import hmac
from string import letters

import webapp2
import jinja2

from google.appengine.ext import db

template_dir = os.path.join(os.path.dirname(__file__), 'templates')
jinja_env = jinja2.Environment(loader = jinja2.FileSystemLoader(template_dir),
                               autoescape = False)

secret = 'loquesea'

def render_str(template, **params):
    t = jinja_env.get_template(template)
    return t.render(params)

def make_secure_val(val):
    return '%s|%s' % (val, hmac.new(secret, val).hexdigest())

def check_secure_val(secure_val):
    val = secure_val.split('|')[0]
    if secure_val == make_secure_val(val):
        return val

class WikiHandler(webapp2.RequestHandler):
    def write(self, *a, **kw):
        self.response.out.write(*a, **kw)

    def render_str(self, template, **params):
        params['user'] = self.user
        params['view'] = self.view
        t = jinja_env.get_template(template)
        return t.render(params)

    def render(self, template, **kw):
        self.write(self.render_str(template, **kw))

    def set_secure_cookie(self, name, val):
        cookie_val = make_secure_val(val)
        self.response.headers.add_header(
            'Set-Cookie',
            '%s=%s; Path=/' % (name, cookie_val))

    def read_secure_cookie(self, name):
        cookie_val = self.request.cookies.get(name)
        return cookie_val and check_secure_val(cookie_val)

    def login(self, user):
        self.set_secure_cookie('user_id', str(user.key().id()))

    def logout(self):
        self.response.headers.add_header('Set-Cookie', 'user_id=; Path=/')

    def initialize(self, *a, **kw):
        webapp2.RequestHandler.initialize(self, *a, **kw)
        uid = self.read_secure_cookie('user_id')
        self.user = uid and User.by_id(int(uid))
        self.view = False


##### user stuff
def make_salt(length = 5):
    return ''.join(random.choice(letters) for x in xrange(length))

def make_pw_hash(name, pw, salt = None):
    if not salt:
        salt = make_salt()
    h = hashlib.sha256(name + pw + salt).hexdigest()
    return '%s,%s' % (salt, h)

def valid_pw(name, password, h):
    salt = h.split(',')[0]
    return h == make_pw_hash(name, password, salt)

def users_key(group = 'default'):
    return db.Key.from_path('users', group)

class User(db.Model):
    name = db.StringProperty(required = True)
    pw_hash = db.StringProperty(required = True)
    email = db.StringProperty()

    @classmethod
    def by_id(cls, uid):
        return User.get_by_id(uid, parent = users_key())

    @classmethod
    def by_name(cls, name):
        u = User.all().filter('name =', name).get()
        return u

    @classmethod
    def register(cls, name, pw, email = None):
        pw_hash = make_pw_hash(name, pw)
        return User(parent = users_key(),
                    name = name,
                    pw_hash = pw_hash,
                    email = email)

    @classmethod
    def login(cls, name, pw):
        u = cls.by_name(name)
        if u and valid_pw(name, pw, u.pw_hash):
            return u


##### blog stuff
def blog_key(name = 'default'):
    return db.Key.from_path('blogs', name)

class Wiki(db.Model):
	subject = db.StringProperty(required = True)
	content = db.TextProperty(required = True)
	created = db.DateTimeProperty(auto_now_add = True)
	last_modified = db.DateTimeProperty(auto_now = True)
	name = db.StringProperty()
	email = db.StringProperty()

	def get_id(self):
		return self.key().id()
		
	def render(self, wikiPage):
		self.content = cgi.escape(self.content)
		params = dict(p=self, wikiPage = wikiPage)
		return render_str("table.html", **params)

class EditPage(WikiHandler):
	def get(self, wikiPage):
		content = ""
		
		if self.user:
			v = self.request.get('v')
			if v:
				key = db.Key.from_path('Wiki', int(v))
				wiki = db.get(key)
				content = wiki.content
			else:
				q = Wiki.gql("WHERE subject = '%s' ORDER BY created DESC" % wikiPage)
				result = q.get()
				if result:
					content = result.content
					
			params = {}
			params['wikiPage'] = wikiPage
			params['content'] = content
			self.render("editWiki.html", **params)
		else:
			self.redirect("/login")

	def post(self, wikiPage):
		content = self.request.get('content').replace('/n', '<br>')
		
		if content:
			w = Wiki(subject = wikiPage, content = content, name = self.user.name, email = self.user.email)
			w.put()
			self.redirect(wikiPage)
		else:
			error = "content, please!"
			self.render("editWiki.html", error=error)

class HistoryPage(WikiHandler):
	def get(self, wikiPage):
		if self.user:
			self.view = True
			q =  Wiki.gql("WHERE subject = '%s' ORDER BY created DESC" % wikiPage)
			params = dict(history = q,
                     wikiPage = wikiPage)
			self.render("historyWiki.html", **params)
		else:
			self.redirect("/login")

                
class WikiPage(WikiHandler):
	def get(self, wikiPage):
		params = {}
		content = ""
		
		v = self.request.get('v')
		if v:
			key = db.Key.from_path('Wiki', int(v))
			wiki = db.get(key)
			content = wiki.content
			params['v'] = v
		else:
			q = Wiki.gql("WHERE subject = '%s' ORDER BY created DESC" % wikiPage)
			result = q.get()
			
			if not result:
				self.redirect("/_edit" + wikiPage)
			else:
				content = result.content
					
		params['wikiPage'] = wikiPage
		params['content'] = content
		self.render("wiki.html", **params)

USER_RE = re.compile(r"^[a-zA-Z0-9_-]{3,20}$")
def valid_username(username):
    return username and USER_RE.match(username)

PASS_RE = re.compile(r"^.{3,20}$")
def valid_password(password):
    return password and PASS_RE.match(password)

EMAIL_RE  = re.compile(r'^[\S]+@[\S]+\.[\S]+$')
def valid_email(email):
    return not email or EMAIL_RE.match(email)

class Signup(WikiHandler):
    def get(self):
        self.render("signup-form.html")

    def post(self):
        have_error = False
        self.username = self.request.get('username')
        self.password = self.request.get('password')
        self.verify = self.request.get('verify')
        self.email = self.request.get('email')

        params = dict(username = self.username,
                      email = self.email)

        if not valid_username(self.username):
            params['error_username'] = "That's not a valid username."
            have_error = True

        if not valid_password(self.password):
            params['error_password'] = "That wasn't a valid password."
            have_error = True
        elif self.password != self.verify:
            params['error_verify'] = "Your passwords didn't match."
            have_error = True

        if not valid_email(self.email):
            params['error_email'] = "That's not a valid email."
            have_error = True

        if have_error:
            self.render('signup-form.html', **params)
        else:
            self.done()

    def done(self, *a, **kw):
        raise NotImplementedError

class Register(Signup):
    def done(self):
        #make sure the user doesn't already exist
        u = User.by_name(self.username)
        if u:
            msg = 'That user already exists.'
            self.render('signup-form.html', error_username = msg)
        else:
            u = User.register(self.username, self.password, self.email)
            u.put()

            self.login(u)
            self.redirect('/')

class Login(WikiHandler):
    def get(self):
        self.render('login-form.html')

    def post(self):
        username = self.request.get('username')
        password = self.request.get('password')

        u = User.login(username, password)
        if u:
            self.login(u)
            self.redirect('/')
        else:
            msg = 'Invalid login'
            self.render('login-form.html', error = msg)

class Logout(WikiHandler):
    def get(self):
        self.logout()
        self.redirect('/login')

PAGE_RE = r'(/(?:[a-zA-Z0-9_-]+/?)*)'
app = webapp2.WSGIApplication([('/signup', Register),
                               ('/login', Login),
                               ('/logout', Logout),
                               ('/_edit' + PAGE_RE, EditPage),
                               ('/_history' + PAGE_RE, HistoryPage),
                               (PAGE_RE, WikiPage),
                               ],
                              debug=True)
