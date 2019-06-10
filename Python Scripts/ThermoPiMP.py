#!/usr/bin/python3

import sys

def savePlot(fname=None,q=None,d=None,fastLog=None,minutesLog=None,hoursLog=None,daysLog=None):
	if fname is None:
		return 3
	
	from queue import Empty
	from multiprocessing import Queue, Manager
	
	from math import ceil
	from time import time, localtime, strftime

	# Import & Initialize plotting module
	import matplotlib
	matplotlib.use('Agg')
	from matplotlib import pyplot as plt

	plt.ioff()

	class TempLog():
		def __init__(self):
			self.numEntries = 0
			self.T1 = []
			self.T1Ambient = []
			self.T2 = []
			self.T2Ambient = []
			self.TimeStamp = []
	
	if q is not None: # Acquire data passed via mp.Queue
		fastLog = TempLog()
		minutesLog = TempLog()
		hoursLog = TempLog()
		daysLog = TempLog()
		try:
			fastLog.T1 = q.get(block=True,timeout=15)
			fastLog.T1Ambient = q.get(block=True,timeout=15)
			fastLog.T2 = q.get(block=True,timeout=15)
			fastLog.T2Ambient = q.get(block=True,timeout=15)
			fastLog.TimeStamp = q.get(block=True,timeout=15)
			
			minutesLog.T1 = q.get(block=True,timeout=15)
			minutesLog.T1Ambient = q.get(block=True,timeout=15)
			minutesLog.T2 = q.get(block=True,timeout=15)
			minutesLog.T2Ambient = q.get(block=True,timeout=15)
			minutesLog.TimeStamp = q.get(block=True,timeout=15)
			
			hoursLog.T1 = q.get(block=True,timeout=15)
			hoursLog.T1Ambient = q.get(block=True,timeout=15)
			hoursLog.T2 = q.get(block=True,timeout=15)
			hoursLog.T2Ambient = q.get(block=True,timeout=15)
			hoursLog.TimeStamp = q.get(block=True,timeout=15)
			
			daysLog.T1 = q.get(block=True,timeout=15)
			daysLog.T1Ambient = q.get(block=True,timeout=15)
			daysLog.T2 = q.get(block=True,timeout=15)
			daysLog.T2Ambient = q.get(block=True,timeout=15)
			daysLog.TimeStamp = q.get(block=True,timeout=15)
		except Empty as e:
			pass
			return 2
		except Exception as e:
			return 1
	elif d is not None: # Acquire data passed via Manager.dict
		fastLog = TempLog()
		minutesLog = TempLog()
		hoursLog = TempLog()
		daysLog = TempLog()
		
		# print(type(d['fastLogT1']))
		
		# fastLog.T1 = d['fastLogT1']
		# fastLog.T1Ambient = d['fastLogT1Ambient']
		# fastLog.T2 = d['fastLogT2']
		# fastLog.T2Ambient = d['fastLogT2Ambient']
		# fastLog.TimeStamp = d['fastLogTimeStamp']
		
		minutesLog.T1 = d['minutesLogT1']
		minutesLog.T1Ambient = d['minutesLogT1Ambient']
		minutesLog.T2 = d['minutesLogT2']
		minutesLog.T2Ambient = d['minutesLogT2Ambient']
		minutesLog.TimeStamp = d['minutesLogTimeStamp']
		
		hoursLog.T1 = d['hoursLogT1']
		hoursLog.T1Ambient = d['hoursLogT1Ambient']
		hoursLog.T2 = d['hoursLogT2']
		hoursLog.T2Ambient = d['hoursLogT2Ambient']
		hoursLog.TimeStamp = d['hoursLogTimeStamp']
		
		daysLog.T1 = d['daysLogT1']
		daysLog.T1Ambient = d['daysLogT1Ambient']
		daysLog.T2 = d['daysLogT2']
		daysLog.T2Ambient = d['daysLogT2Ambient']
		daysLog.TimeStamp = d['daysLogTimeStamp']
	elif fastLog is None or minutesLog is None or hoursLog is None or daysLog is None:
		pass
		return 3
	sys.stdout.write('Generating plot: {}\n'.format(fname))
	sys.stdout.flush()
	fig = plt.figure()
	fig.set_size_inches(32,8)
	fig.set_dpi(200)
	# ts = fastLog.TimeStamp[-7200:]
	# if len(ts) > 0:
		# t1 = fastLog.T1[-7200:]
		# t1amb = fastLog.T1Ambient[-7200:]
		# t2 = fastLog.T2[-7200:]
		# t2amb = fastLog.T2Ambient[-7200:]
		# plt.subplot(2,4,1)
		# initTime = ts[0]
		# for ii in range(len(ts)):
			# ts[ii] -= initTime
		# plt.xlabel('ROOM: Seconds since ' + strftime('%Y-%m-%d %H:%M:%S',localtime(initTime)))
		# plt.ylabel('Degrees C')
		# plt.plot(ts,t1amb,'r',ts,t2amb,'b')
		# plt.subplot(2,4,5)
		# plt.xlabel('TANK: Seconds since ' + strftime('%Y-%m-%d %H:%M:%S',localtime(initTime)))
		# plt.ylabel('Degrees C')
		# plt.plot(ts,t1,'r',ts,t2,'b',)
		# plt.ylim(-200,ceil(max([max(t1),max(t2)])))
	# else:
		# print('No FastLog')
	
	ts = minutesLog.TimeStamp[:]	
	if len(ts) > 0:
		t1 = minutesLog.T1[:]
		t1amb = minutesLog.T1Ambient[:]
		t2 = minutesLog.T2[:]
		t2amb = minutesLog.T2Ambient[:]
		# plt.subplot(2,4,2)
		plt.subplot(2,3,1)
		initTime = ts[0]
		for ii in range(len(ts)):
			ts[ii] = round((ts[ii] - initTime) / 60)
		plt.xlabel('ROOM: Minutes since ' + strftime('%Y-%m-%d %H:%M',localtime(initTime)))
		plt.ylabel('Degrees C')
		plt.plot(ts,t1amb,'r',ts,t2amb,'b')
		# plt.subplot(2,4,6)
		plt.subplot(2,3,4)
		plt.xlabel('TANK: Minutes since ' + strftime('%Y-%m-%d %H:%M',localtime(initTime)))
		plt.ylabel('Degrees C')
		plt.plot(ts,t1,'r',ts,t2,'b',)
		# plt.ylim(-200,ceil(max([max(t1),max(t2)])))
	else:
		print('No MinutesLog')
	
	ts = hoursLog.TimeStamp[:]
	if len(ts) > 0:
		t1 = hoursLog.T1[:]
		t1amb = hoursLog.T1Ambient[:]
		t2 = hoursLog.T2[:]
		t2amb = hoursLog.T2Ambient[:]
		# plt.subplot(2,4,3)
		plt.subplot(2,3,2)
		initTime = ts[0]
		for ii in range(len(ts)):
			ts[ii] = round((ts[ii] - initTime) / 3600)
		plt.xlabel('ROOM: Hours since ' + strftime('%Y-%m-%d %H:%M',localtime(initTime)))
		plt.ylabel('Degrees C')
		plt.plot(ts,t1amb,'r',ts,t2amb,'b')
		# plt.subplot(2,4,7)
		plt.subplot(2,3,5)
		plt.xlabel('TANK: Hours since ' + strftime('%Y-%m-%d %H:%M',localtime(initTime)))
		plt.ylabel('Degrees C')
		plt.plot(ts,t1,'r',ts,t2,'b',)
		# plt.ylim(-200,ceil(max([max(t1),max(t2)])))
	else:
		print('No HoursLog')
	
	ts = daysLog.TimeStamp[:]
	if len(ts) > 0:
		t1 = daysLog.T1[:]
		t1amb = daysLog.T1Ambient[:]
		t2 = daysLog.T2[:]
		t2amb = daysLog.T2Ambient[:]
		# plt.subplot(2,4,4)
		plt.subplot(2,3,3)
		initTime = ts[0]
		for ii in range(len(ts)):
			ts[ii] = round((ts[ii] - initTime) / 43200)
		plt.xlabel('ROOM: Days since ' + strftime('%Y-%m-%d',localtime(initTime)))
		plt.ylabel('Degrees C')
		plt.plot(ts,t1amb,'r',ts,t2amb,'b')
		# plt.subplot(2,4,8)
		plt.subplot(2,3,6)
		plt.xlabel('Days since ' + strftime('%Y-%m-%d',localtime(initTime)))
		plt.ylabel('Degrees C')
		plt.plot(ts,t1,'r',ts,t2,'b',)
		# plt.ylim(-200,ceil(max([max(t1),max(t2)])))
	else:
		print('No DaysLog')
	
	sys.stdout.write('Saving plot: {}\n'.format(fname))
	sys.stdout.flush()
	plt.savefig(fname, bbox_inches='tight')
	plt.close()
	return fname

def emailFile(fname,emailaddress,body=None):
	# Import email modules
	import smtplib, mimetypes
	from email.message import EmailMessage
	from email.mime.text import MIMEText
	msg = EmailMessage()
	msg['Subject'] = 'LN Monitor Log'
	msg['From'] = 'LN Monitor<robinsonlabiot@gmail.com>'
	msg['To'] = emailaddress
	if body is not None:
		msg.attach(MIMEText(body))
	ctype, encoding = mimetypes.guess_type(fname)
	if ctype is None or encoding is not None:
		ctype = 'application/octet-stream'
	maintype, subtype = ctype.split('/',1)
	print('Adding log attachment')
	with open(fname,'rb') as fid:
		msg.add_attachment(fid.read(),maintype=maintype,subtype=subtype,filename=fname)
	with smtplib.SMTP_SSL('smtp.gmail.com',465) as gmail:
		gmail.login('robinsonlabiot@gmail.com','brainlabGRB121')
		gmail.send_message(msg)
