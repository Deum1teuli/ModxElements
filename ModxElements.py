# -*- coding: utf-8 -*-

import sublime, sublime_plugin
import urllib, http.cookies
import contextlib, tempfile, functools, traceback

def plugin_loaded():
	global settings

	settings = sublime.load_settings('ModxElements.sublime-settings')

# Exceptions
class MissingCredentialsException(Exception):
	pass

class MissingServerException(Exception):
	pass

class ModxApiException(Exception):
	def __init__(self, response):
		self.response = response

def catch_errors(fn):
	@functools.wraps(fn)
	def _fn(*args, **kwargs):
		try:
			return fn(*args, **kwargs)
		except MissingCredentialsException:
			sublime.error_message('ModxElements: Server is not authorized.')
			# sublime.active_window().run_command('modx_server_set')
		except MissingServerException:
			sublime.error_message('ModxElements: Server is not set.')
			# sublime.active_window().run_command('modx_server_set')
		except ModxApiException as e:
			error_string = e.response['data'][0]['msg']
			sublime.error_message('ModxElements: %s' % error_string)
		except:
			traceback.print_exc()
			sublime.error_message("ModxElements: unknown error (please, report a bug!)")

	return _fn

# Help functions
def api_request(url='/connectors/index.php', **data):
	server = settings.get('server_address')
	if not server:
		raise MissingServerException()
	url = urllib.parse.urljoin(server, url)
	session = settings.get('server_session')
	token = settings.get('server_token')

	data['HTTP_MODAUTH'] = token
	request = urllib.request.Request(url, urllib.parse.urlencode(data).encode(), method='POST')
	if session:
		request.add_header('Cookie', session)
	if token:
		request.add_header('modAuth', token)
	try:
		with contextlib.closing(urllib.request.urlopen(request)) as response:
			if response.getheader('Set-Cookie'):
				cookie = http.cookies.SimpleCookie()
				cookie.load(response.getheader('Set-Cookie'))
				settings.set('server_session', 'PHPSESSID=' + cookie['PHPSESSID'].value)
			response_raw = response.read().decode('utf8')
			response_data = sublime.decode_value(response_raw)
			if not response_data['success']:
				if 'code' in response_data['object'] and response_data['object']['code'] == 401:
					raise MissingCredentialsException()
				else:
					raise ModxApiException(response_data)
			return response_data
	except urllib.error.HTTPError as e:
		if e.code == 401:
			raise MissingCredentialsException()
		else:
			raise e

def open_element(element_class, element):
	view = sublime.active_window().new_file()

	if (element_class in ('modSnippet', 'modPlugin')):
		view.run_command('append', {
			'characters': '<?php\n',
		})
	view.run_command('append', {
		'characters': element['content'],
	})

	modify_view(view, element_class, element)

def close_element(element_class, element_id):
	for window in sublime.windows():
		for view in window.views():
			if view.settings().get('modx_element_class') == element_class \
			and view.settings().get('modx_element_id') == element_id:
				unmodify_view(view)

def modify_view(view, element_class, element):
	# view.set_scratch(True)
	view.retarget(tempfile.gettempdir() + '/' + element['name'])
	view.settings().set('modx_do_update', False)
	view.run_command('save')
	view.set_syntax_file(settings.get('syntax').get(element_class))

	view.settings().set('modx_element_class', element_class)
	view.settings().set('modx_element_id', element['id'])
	view.settings().set('modx_element_name', element['name'])
	view.settings().set('modx_element_description', element['description'])
	view.set_status('Modx', 'Modx Element (%s): %s' % (element_class, element['name']))

def unmodify_view(view):
	# view.set_scratch(False)
	# view.retarget('')

	view.settings().erase('modx_element_class')
	view.settings().erase('modx_element_id')
	view.settings().erase('modx_element_name')
	view.settings().erase('modx_element_description')
	view.erase_status('Modx')

def element_class_select(context, command):
	window = sublime.active_window()

	element_classes = [
	{'name': 'Template', 'class': 'modTemplate'},
	{'name': 'Chunk', 'class': 'modChunk'},
	{'name': 'Snippet', 'class': 'modSnippet'},
	{'name': 'Plugin', 'class': 'modPlugin'},
	]

	def on_element_class_num(element_class_num):
		context.run_command(command, {'element_class': element_classes[element_class_num]['class']})

	window.show_quick_panel([element_class['name'] for element_class in element_classes], on_element_class_num)

# Base command classes
class ElementView:
	def __init__(self, view=None):
		if view:
			self.view = view

	def is_enabled(self):
		return bool(self.el_class() and self.el_name() and self.el_id())

	def el_action(self, action, element_class=None):
		element_class = element_class if element_class else self.el_class()
		if element_class == 'modTemplate':
			return 'element/template/%s' % action
		elif element_class == 'modChunk':
			return 'element/chunk/%s' % action
		elif element_class == 'modSnippet':
			return 'element/snippet/%s' % action
		elif element_class == 'modPlugin':
			return 'element/plugin/%s' % action
		else:
			return None

	def el_id(self):
		return self.view.settings().get('modx_element_id')

	def el_class(self):
		return self.view.settings().get('modx_element_class')

	def el_name(self):
		return self.view.settings().get('modx_element_name')

	def el_description(self):
		return self.view.settings().get('modx_element_description')

	def el_content(self):
		return self.view.substr(sublime.Region(0, self.view.size()))

	def el_do_update(self):
		return self.view.settings().get('modx_do_update')

# Server commands
class ModxServerSetCommand(sublime_plugin.WindowCommand):
	def run(self):
		server = {'rememberme': 1}

		def on_server_address(server_address):
			server['address'] = server_address
			self.window.show_input_panel('Modx Server Username', '', on_server_username, None, None)

		def on_server_username(server_username):
			server['username'] = server_username
			self.window.show_input_panel('Modx Server Password', '', on_server_password, None, None)

		@catch_errors
		def on_server_password(server_password):
			server['password'] = server_password
			server['action'] = 'security/login'
			settings.set('server_address', server['address'])
			response = api_request('/connectors/', **server)
			settings.set('server_token', response['object']['token'])
			sublime.save_settings('ModxElements.sublime-settings')
			sublime.status_message('Modx Server saved')

		self.window.show_input_panel('Modx Server Address', settings.get('server_address', 'http://'), on_server_address, None, None)

# List commands
class ModxElementOpenCommand(sublime_plugin.WindowCommand):
	@catch_errors
	def run(self, element_class=None, element_name=None):
		if not element_class:
			element_class_select(self.window, 'modx_element_open')
			return

		response = api_request(action='element/getlistbyclass', limit=0, element_class=element_class)
		elements = response['results']

		element_key = 0
		if element_name:
			elements_by_name = [element_key for element_key, element in enumerate(elements) if element['name'].lower() == element_name.lower()]
			if len(elements_by_name) > 0:
				element_key = elements_by_name[0]

		def on_element_num(element_num):
			if element_num > -1:
				element = elements[element_num]
				open_element(element_class, element)

		self.window.show_quick_panel(
			[element['name'] for element in elements], on_element_num, 0, element_key
		)

class ModxElementSelectedOpen(sublime_plugin.TextCommand):
	def is_enabled(self):
		return \
		self.view.match_selector(self.view.sel()[0].begin(), 'entity.name.tag.chunk.modx') \
		or self.view.match_selector(self.view.sel()[0].begin(), 'entity.name.tag.snippet.modx')

	def run(self, edit):
		element_class = None
		if self.view.match_selector(self.view.sel()[0].begin(), 'entity.name.tag.chunk.modx'):
			element_class = 'modChunk'
		elif self.view.match_selector(self.view.sel()[0].begin(), 'entity.name.tag.snippet.modx'):
			element_class = 'modSnippet'
		if element_class:
			element_name = self.view.substr(self.view.extract_scope(self.view.sel()[0].begin()))
			self.view.window().run_command('modx_element_open', {
				'element_class': element_class,
				'element_name': element_name
				})

# Element commands
class ModxElementCreateCommand(sublime_plugin.TextCommand):
	@catch_errors
	def run(self, edit, element_class=None):
		if not element_class:
			element_class_select(self.view, 'modx_element_create')
			return

		element_view = ElementView(self.view)
		regions = [region for region in self.view.sel() if not region.empty()]
		if len(regions) == 0:
			region_data = [element_view.el_content()]
		else:
			region_data = [self.view.substr(region) for region in regions]

		response = api_request(action='element/category/getlist')
		categories = [{'name': 'No category', 'id': ''}] + response['results']
		element = {}

		def on_element_name(element_name):
			if element_name:
				if element_class in ('modTemplate'):
					element['templatename'] = element_name
				else:
					element['name'] = element_name

				self.view.window().show_input_panel('Modx Element Description (optional):', '', on_element_description, None, None)

		def on_element_description(element_description):
			element['description'] = element_description

			self.view.window().show_quick_panel(
				[category['name'] for category in categories], on_category_num
			)

		@catch_errors
		def on_category_num(category_num):
			if category_num > -1:
				element['category'] = categories[category_num]['id']
				if element_class in ('modTemplate'):
					element['content'] = ''.join(region_data)
				elif element_class in ('modPlugin'):
					element['plugincode'] = ''.join(region_data)
				else:
					element['snippet'] = ''.join(region_data)

				response = api_request(action=element_view.el_action('create', element_class), **element)

				if element_class in ('modChunk') and len(regions) == 1:
					self.view.run_command('modx_replace', {
						'region': (regions[0].a, regions[0].b),
						'characters': '[[$%s]]' % response['object']['name']
						})
				elif len(regions) == 0:
					element.update(response['object'])
					modify_view(self.view, element_class, element)
				sublime.status_message('Modx Element created')

		self.view.window().show_input_panel('Modx Element Name:', element_view.el_name() or '', on_element_name, None, None)

class ModxElementUpdateCommand(ElementView, sublime_plugin.TextCommand):
	def run(self, edit):
		response = api_request(action='element/category/getlist')
		categories = [{'name': 'No category', 'id': ''}] + response['results']
		element = {'id': self.el_id()}

		def on_element_name(element_name):
			if element_name:
				if self.el_class() in ('modTemplate'):
					element['templatename'] = element_name
				else:
					element['name'] = element_name

				self.view.window().show_input_panel('Modx Element Description (optional):', self.el_description() or '', on_element_description, None, None)

		def on_element_description(element_description):
			element['description'] = element_description

			self.view.window().show_quick_panel(
				[category['name'] for category in categories], on_category_num
			)

		@catch_errors
		def on_category_num(category_num):
			if category_num > -1:
				element['category'] = categories[category_num]['id']
				response = api_request(action=self.el_action('update', self.el_class()), **element)
				element.update(response['object'])				
				modify_view(self.view, self.el_class(), element)
				sublime.status_message('Modx Element updated')

		self.view.window().show_input_panel('Modx Element Name:', self.el_name() or '', on_element_name, None, None)

class ModxElementRemoveCommand(ElementView, sublime_plugin.TextCommand):
	@catch_errors
	def run(self, edit):
		response = api_request(action=self.el_action('remove'), id=self.el_id())
		close_element(self.el_class(), response['object']['id'])
		sublime.status_message('Modx element deleted')

class ModxElementListener(sublime_plugin.EventListener):
	@catch_errors
	def on_pre_save_async(self, view):
		element_view = ElementView(view)
		if element_view.el_do_update() and element_view.is_enabled():
			if element_view.el_class() in ('modTemplate'):
				api_request(action=element_view.el_action('update'), templatename=element_view.el_name(), id=element_view.el_id(), content=element_view.el_content())
			elif element_view.el_class() in ('modPlugin'):
				api_request(action=element_view.el_action('update'), name=element_view.el_name(), id=element_view.el_id(), plugincode=element_view.el_content())
			else:
				api_request(action=element_view.el_action('update'), name=element_view.el_name(), id=element_view.el_id(), snippet=element_view.el_content())
			sublime.status_message('Modx Element updated')
		if not element_view.el_do_update() and element_view.is_enabled():
			view.settings().set('modx_do_update', True)

# Other commands
class ModxReplaceCommand(sublime_plugin.TextCommand):
	def run(self, edit, region, characters):
		self.view.replace(edit, sublime.Region(*region), characters)