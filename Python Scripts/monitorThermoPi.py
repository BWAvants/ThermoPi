#!/usr/bin/python3

import socket, sys
from select import select
from time import sleep
import threading

running = True

sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

s1Text = 'S1:     ,     ,     ,     '
s2Text = 'S2:     ,     ,     ,     '
amText = 'Ambient1: **.***  Ambient2: **.***'
tpText = 'T1: -***.***  T2: -***.***'

def keyboardListener():
	global running, sock
	email = False
	display = False
	message = ''
	response = ''
	while running:
		entry = sys.stdin.readline()
		if entry.find('exit') > -1:
			message = 'drop'
			running = False
		elif entry.find('stop') > -1:
			message = 'stop'
		elif entry.find('plot') > -1:
			message = 'plot:'
		elif entry.find('email') > -1:
			message = 'email:'
			if entry.find('seconds'):
				message += 'seconds'
			elif entry.find('minutes'):
				message += 'minutes'
			elif entry.find('hours'):
				message += 'hours'
			elif entry.find('days'):
				message += 'days'
		elif entry.find('save') > -1:
			message = 'save:'
			if 'json' in entry:
				message += 'json'
		elif entry.find('linearize') > -1:
			message = 'linearize:'
			if entry.find('on') > -1:
				message += 'on'
		elif 'redraw' in entry:
			drawDisplay()
			continue
		if len(message) > 0:
			try:
				sock.sendall(message.encode('utf-8'))
			except:
				sys.stdout.write("\033[F\033[K")
				print('SENDING FAILED',end='')
				sys.stdout.flush()
				sleep(1)
			message = ''
		sys.stdout.write("\033[F\033[K")
		print('mTP:> ',end='',flush=True)

keyListener = threading.Thread(target=keyboardListener,daemon=True)
keyListener.start()

try:
	sock.connect('./ThermoPi.pe')
except socket.error as msg:
	print(msg)
	sys.exit(1)
	

def drawDisplay():
	sys.stdout.write("\033[2J")
	sys.stdout.flush()
	sys.stdout.write("\033[1;0H\033[2J") # Title on line 1
	print('ThermoPi monitor',end='')
	sys.stdout.write("\033[2;0H") # Status labels on line 2
	print('  NoProbe  GND  VCC  fault',end='')
	sys.stdout.write("\033[3;0H") # Status 1 on line 3
	print(s1Text,end='')
	sys.stdout.write("\033[4;0H") # Status 2 on line 4
	print(s2Text,end='')
	sys.stdout.write("\033[5;0H") # Ambients on line 5
	print(amText,end='')
	sys.stdout.write("\033[6;0H") # Temps on line 6
	print(tpText,end='')
	sys.stdout.write("\033[7;0H") # Prompt on line 7
	print('mTP:> ',end='')
	sys.stdout.flush()


incoming = ''
message = ''

try:
	drawDisplay()
	while running:
		r,w,e = select([sock],[],[],1)
		if r:
			incoming += sock.recv(1024).decode('utf-8')
			while '\a' in incoming:
				message, incoming = incoming.split('\a',1)
				if 'T1:' in message:
					tpText = message
					sys.stdout.write("\033[s\033[6;0H\033[K")
					print(message,end='')
					sys.stdout.write("\033[u")
					sys.stdout.flush()
				elif 'Ambient1:' in message:
					amText = message
				elif 'S1:' in message:
					s1Text = message
				elif 'S2:' in message:
					s2Text = message
					drawDisplay()
		else:
			sys.stdout.write("\033[s\033[6;0H\033[K")
			print('No message',end='')
			sys.stdout.write("\033[u")
			sys.stdout.flush()
finally:
	sock.close()
	sys.stdout.write("\033[1A\033[100D\033[K")
	print("Monitor Closing... ",end='',flush=True)
	keyListener.join(1)
	print('Done')
