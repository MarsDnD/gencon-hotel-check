#!/usr/bin/python
from argparse import Action, ArgumentParser, ArgumentTypeError, SUPPRESS
from datetime import datetime
from HTMLParser import HTMLParser
from json import loads as fromJS
from ssl import create_default_context as create_ssl_context, CERT_NONE, SSLError
from threading import Thread
from time import sleep
from urllib import urlencode
from urllib2 import Request, URLError, urlopen
import urllib, urllib2

distanceUnits = {
	1: 'blocks',
	2: 'yards',
	3: 'miles',
	4: 'meters',
	5: 'kilometers',
}

class PasskeyParser(HTMLParser):
	def __init__(self, resp):
		HTMLParser.__init__(self)
		self.json = None
		self.feed(resp.read())
		self.close()

	def handle_starttag(self, tag, attrs):
		if tag.lower() == 'script':
			attrs = dict(attrs)
			if attrs.get('id', '').lower() == 'last-search-results':
				self.json = True

	def handle_data(self, data):
		if self.json is True:
			self.json = data

firstDay, lastDay = datetime(2016, 7, 30), datetime(2016, 8, 9)
def type_day(arg):
	try:
		d = datetime.strptime(arg, '%Y-%m-%d')
	except ValueError:
		raise ArgumentTypeError("%s is not a date in the form YYYY-MM-DD" % arg)
	if not firstDay <= d <= lastDay:
		raise ArgumentTypeError("%s is outside the Gencon housing block window" % arg)
	return arg

class EmailAction(Action):
	def __call__(self, parser, namespace, values, option_string=None):
		dest = getattr(namespace, self.dest)
		if dest is None:
			dest = []
			setattr(namespace, self.dest, dest)
		dest.append(tuple(['email'] + values))

parser = ArgumentParser()
validDays = ["2016-08-%02d" % d for d in range(1, 10)]
parser.add_argument('--guests', type = int, default = 1, help = 'number of guests')
parser.add_argument('--children', type = int, default = 0, help = 'number of children')
parser.add_argument('--rooms', type = int, default = 1, help = 'number of rooms')
group = parser.add_mutually_exclusive_group()
group.add_argument('--checkin', type = type_day, metavar = 'YYYY-MM-DD', default = '2016-08-04', help = 'check in')
group.add_argument('--wednesday', dest = 'checkin', action = 'store_const', const = '2016-08-03', help = 'check in on 2016-08-03')
parser.add_argument('--checkout', type = type_day, metavar = 'YYYY-MM-DD', default = '2016-08-07', help = 'check out')
parser.add_argument('--max-distance', type = float, metavar = 'BLOCKS', help = 'max hotel distance that triggers an alert')
parser.add_argument('--ssl-insecure', action = 'store_false', dest = 'ssl_cert_verify', help = SUPPRESS)
group = parser.add_mutually_exclusive_group()
group.add_argument('--delay', type = int, default = 1, metavar = 'MINS', help = 'search every MINS minute(s)')
group.add_argument('--once', action = 'store_true', help = 'search once and exit')
parser.add_argument('--test', action = 'store_true', dest = 'test', help = 'trigger every specified alert and exit')

group = parser.add_argument_group('required arguments')
group.add_argument('--key', required = True, help = 'key (see the README for more information)')

group = parser.add_argument_group('alerts')
group.add_argument('--popup', dest = 'alerts', action = 'append_const', const = ('popup',), help = 'show a dialog box')
group.add_argument('--cmd', dest = 'alerts', action = 'append', type = lambda arg: ('cmd', arg), metavar = 'CMD', help = 'run the specified command, passing each hotel name as an argument')
group.add_argument('--browser', dest = 'alerts', action = 'append_const', const = ('browser',), help = 'open the Passkey website in the default browser')
group.add_argument('--email', dest = 'alerts', action = EmailAction, nargs = 3, metavar = ('HOST', 'FROM', 'TO'), help = 'send an e-mail')

args = parser.parse_args()
startUrl = "https://aws.passkey.com/reg/%s/null/null/1/0/null" % args.key

# Setup the alert handlers
alertFns = []
success = True
for alert in args.alerts or []:
	if alert[0] == 'popup':
		try:
			import win32api
			alertFns.append(lambda preamble, hotels: win32api.MessageBox(0, 'Gencon Hotel Search', "%s\n\n%s" % (preamble, '\n'.join("%s: %s" % (hotel['distance'], hotel['name']) for hotel in hotels))))
		except ImportError:
			try:
				import Tkinter, tkMessageBox
				def handle(preamble, hotels):
					window = Tkinter.Tk()
					window.wm_withdraw()
					tkMessageBox.showinfo(title = 'Gencon Hotel Search', message = "%s\n\n%s" % (preamble, '\n'.join("%s: %s" % (hotel['distance'], hotel['name']) for hotel in hotels)))
					window.destroy()
				alertFns.append(handle)
			except ImportError:
				print "Unable to show a popup. Install either win32api (if on Windows) or Tkinter"
				success = False
	elif alert[0] == 'cmd':
		import subprocess
		alertFns.append(lambda preamble, hotels, cmd = alert[1]: subprocess.Popen([cmd] + [hotel['name'] for hotel in hotels]))
	elif alert[0] == 'browser':
		import webbrowser
		alertFns.append(lambda preamble, hotels: webbrowser.open(startUrl))
	elif alert[0] == 'email':
		from email.mime.text import MIMEText
		import getpass, smtplib, socket
		_, host, fromEmail, toEmail = alert
		password = getpass.getpass("Enter password for %s (or blank if %s requires no authentication): " % (fromEmail, host))
		def smtpConnect():
			try:
				smtp = smtplib.SMTP_SSL(host)
			except socket.error:
				smtp = smtplib.SMTP(host)
			if password:
				smtp.login(fromEmail, password)
			return smtp
		try:
			smtpConnect()
			def handle(preamble, hotels):
				msg = MIMEText("%s:\n\n%s\n\n%s" % (preamble, '\n'.join("  * %s: %s" % (hotel['distance'], hotel['name']) for hotel in hotels), startUrl))
				msg['Subject'] = 'Gencon Hotel Search'
				msg['From'] = fromEmail
				msg['To'] = toEmail
				smtpConnect().sendmail(fromEmail, toEmail, msg.as_string())
			alertFns.append(handle)
		except Exception, e:
			print e
			success = False

if not success:
	exit(1)
if not alertFns:
	print "Warning: You have no alert methods selected, so you're not going to know about a match unless you're staring at this window when it happens. See the README for more information"
	print

if args.test:
	print "Testing alerts one at a time..."
	preamble = 'This is a test'
	hotels = [{'name': 'Test hotel 1', 'distance': '2 blocks'}, {'name': 'Test hotel 2', 'distance': '5 blocks'}]
	for fn in alertFns:
		fn(preamble, hotels)
	print "Done"
	exit(0)

sslCtx = create_ssl_context()
if not args.ssl_cert_verify:
	sslCtx.check_hostname = False
	sslCtx.verify_mode = CERT_NONE

lastAlerts = None

def sessionSetup():
	print "Getting session..."
	try:
		resp = urlopen(startUrl, context = sslCtx)
	except URLError, e:
		if isinstance(e.reason, SSLError) and e.reason.reason == 'CERTIFICATE_VERIFY_FAILED':
			print e
			print
			print "If Python is having trouble finding your local certificate store, you can bypass this check with --ssl-insecure"
			exit(1)
		raise e
	if resp.getcode() != 200:
		print "Request failed: %d" % resp.getcode()
		return None

	if 'Set-Cookie' not in resp.info():
		print "No session cookie received. Is your key correct?"
		return None
	cookies = resp.info()['Set-Cookie'].split(', ')
	cookies = map(lambda cookie: cookie.split(';')[0], cookies)
	headers = {'Cookie': ';'.join(cookies)}

	# Set search filter
	print "Setting search filter... (%d %s, %d %s, %s - %s)" % (args.guests, 'guest' if args.guests == 1 else 'guests', args.rooms, 'room' if args.rooms == 1 else 'rooms', args.checkin, args.checkout)
	data = {
		'hotelId': '0',
		'blockMap.blocks[0].blockId': '0',
		'blockMap.blocks[0].checkIn': args.checkin,
		'blockMap.blocks[0].checkOut': args.checkout,
		'blockMap.blocks[0].numberOfGuests': str(args.guests),
		'blockMap.blocks[0].numberOfRooms': str(args.rooms),
		'blockMap.blocks[0].numberOfChildren': str(args.children),
	}
	resp = urlopen(Request('https://aws.passkey.com/event/14276138/owner/10909638/rooms/select', urlencode(data), headers), context = sslCtx)
	if resp.getcode() not in (200, 302):
		print "Search failed"
		return None

	# Set sort to "distance (near to far)". The response is ignored; it's not a big deal if this fails
	data = {
		'eventInventory': 'false',
		'sortOption': 'ascDistance',
	}
	urlopen(Request('https://aws.passkey.com/event/14276138/owner/10909638/sort/hotel-list', urlencode(data), headers), context = sslCtx)

	# Fetching this page gives the latest results
	return Request('https://aws.passkey.com/event/14276138/owner/10909638/list/hotels', headers = headers)

def search(req):
	global lastAlerts
	print
	print "Loading search results... (%s)" % datetime.now()
	resp = urlopen(req, context = sslCtx)
	if resp.getcode() != 200:
		print "Request failed: %d" % resp.getcode()
		return False

	print "Parsing HTML..."
	parser = PasskeyParser(resp)
	if not parser.json:
		print "Failed to find search results"
		return False

	print "Parsing JSON..."
	hotels = fromJS(parser.json)

	print
	print "Results:"
	alert = []

	for hotel in hotels:
		if hotel['blocks']:
			simpleHotel = {'name': parser.unescape(hotel['name']), 'distance': "%4.1f %s" % (hotel['distanceFromEvent'], distanceUnits.get(hotel['distanceUnit'], '???'))}
			result = "%-15s %s" % (simpleHotel['distance'], simpleHotel['name'])
			# I don't think these distances (yards, meters, kilometers) actually appear in the results, but if they do assume it must be close enough regardless of --max-distance
			if hotel['distanceUnit'] in (2, 4, 5) or (hotel['distanceUnit'] == 1 and (args.max_distance is None or hotel['distanceFromEvent'] <= args.max_distance)):
				alert.append(simpleHotel)
				print ' !',
			else:
				print '  ',
			print result

	if alert:
		if alert == lastAlerts:
			print "Skipped alerts (no change to nearby hotel list)"
		else:
			preamble = "%d %s near the ICC:" % (len(alert), 'hotel' if len(alert) == 1 else 'hotels')
			for fn in alertFns:
				# Run each alert on its own thread since some (e.g. popups) are blocking and some (e.g. e-mail) can throw
				Thread(target = fn, args = (preamble, alert)).start()
			print "Triggered alerts"

	lastAlerts = alert
	return True

while True:
	req = sessionSetup()
	if req is not None:
		while True:
			if not search(req): # Search failed, possibly session timeout? Try connecting again immediately
				break
			if args.once:
				exit(0)
			sleep(60 * args.delay)
	else: # Session setup failed. Try again next cycle
		sleep(60 * args.delay)
