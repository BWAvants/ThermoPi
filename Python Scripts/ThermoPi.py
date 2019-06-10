#!/usr/bin/python3

# The pinout of the ThermoPi chip is inetended to plug directly on the GPIO of the Pi 3 as follows
# SCK		pin 18, GPIO24
# MISO	pin 19, GPIO10
# CS1		pin 21, GPIO09
# CS2		pin 23, GPIO11
# The Adafruit libraries use the GPIO number, not the pin number

# When the chip is opperating between -20 to +85 C, the MAX31855 k-type chip has a thermocouple
# error of +- 2 C from -200 to +700 C, but as much as +-6 in the full range <-270 to +1372>.
#
# At 1 atm. the boiling point of LN is -195.78 C, and higher with more pressure.  This should be
# within the normal operating range of a k-type thermocouple.
#
# There is an additional +-2 C error when reading the ambient temperature, for a total of +- 4 C
# The total precision error should remain fairly constant for a given thermocouple/MAX31855 operating in
# a relatively consistent environment.
# 
# The resolution of the temperature measurement is 0.25 C or 0.45 F
#
# The temperature reading is always ambient temperature compensated and follows the linear conversion:
# T = 41.276 uV * (Tr - Tamb)
# The thermocouple itself is not linear, particularly in the extremes of its range.  It may need compensation.

from time import sleep, time, localtime, strftime, ctime
from threading import Thread, Event, RLock
import multiprocessing as mp
from multiprocessing import Process, Manager, Queue
from select import select
import sys, os, errno, socket, fcntl, math, json, csv, signal
from math import ceil
# import smtplib, mimetypes
# from email.message import EmailMessage

from Adafruit_GPIO import SPI
from Adafruit_MAX31855 import MAX31855 as mx3
# https://github.com/adafruit/Adafruit_Python_MAX31855/blob/master/Adafruit_MAX31855/MAX31855.py


class TermHandler:
	termSig = False
	def __init__(self):
		signal.signal(signal.SIGINT, self.term_rcvd)
		signal.signal(signal.SIGTERM, self.term_rcvd)
	
	def term_rcvd(self,signum,frame):
		sys.stdout.write('TERM Signal Caught\n')
		sys.stdout.flush()
		self.termSig = True


def c_to_f(c):
	return c * 9.0 / 5.0 + 32.0


class TempLog():
	def __init__(self,title='generic',t1=None,t1a=None,t2=None,t2a=None,ts=None):
		self.Title = title
		self.numEntries = 0
		if t1 is not None and t1a is not None and t2 is not None and t2a is not None and ts is not None:
			self.T1 = t1
			self.T1Ambient = t1a
			self.T2 = t2
			self.T2Ambient = t2a
			self.TimeStamp = ts

		else:
			self.T1 = []
			self.T1Ambient = []
			self.T2 = []
			self.T2Ambient = []
			self.TimeStamp = []
	
	def addTemp(self,t1=0,t1ambient=0,t2=0,t2ambient=0,logtime=None):
		if logtime is None:
			self.TimeStamp.append(time())
		else:
			self.TimeStamp.append(logtime)
		self.T1.append(t1)
		self.T1Ambient.append(t1ambient)
		self.T2.append(t2)
		self.T2Ambient.append(t2ambient)
		self.numEntries += 1
	
	def average(self,howMany=None):
		if howMany is None:
			howMany = self.numEntries
		T1 = self.T1[-howMany:]
		t1 = sum(T1) / howMany
		T1A = self.T1Ambient[-howMany:]
		t1ambient = sum(T1A) / howMany
		T2 = self.T2[-howMany:]
		t2 = sum(T2) / howMany
		T2A = self.T2Ambient[-howMany:]
		t2ambient = sum(T2A) / howMany
		TS = self.TimeStamp[-howMany:]
		logtime = sum(TS) / howMany
		return t1, t1ambient, t2, t2ambient, logtime
	
	def max(self,howMany=None):
		if howMany is None:
			howMany = self.numEntries
		T1 = self.T1[-howMany:]
		t1 = max(T1)
		T1A = self.T1Ambient[-howMany:]
		t1ambient = max(T1A)
		T2 = self.T2[-howMany:]
		t2 = max(T2)
		T2A = self.T2Ambient[-howMany:]
		t2ambient = max(T2A)
		TS = self.TimeStamp[-howMany:]
		logtime = sum(TS) / howMany
		return t1, t1ambient, t2, t2ambient, logtime
	
	def purge(self,howMany=0):
		if howMany >= self.numEntries:
			self.T1.clear()
			self.T1Ambient.clear()
			self.T2.clear()
			self.T2Ambient.clear()
			self.TimeStamp.clear()
			self.numEntries = 0
			return
		# self.T1 = self.T1[howMany:]
		# self.T1Ambient = self.T1Ambient[howMany:]
		del self.T1[:howMany]
		del self.T1Ambient[:howMany]
		# self.T2 = self.T2[howMany:]
		# self.T2Ambient = self.T2Ambient[howMany:]
		del self.T2[:howMany]
		del self.T2Ambient[:howMany]
		# self.TimeStamp = self.TimeStamp[howMany:]
		del self.TimeStamp[:howMany]
		self.numEntries = len(self.T1)
	
	def keep_only(self,howMany=None):
		if howMany is None or howMany >= self.numEntries:
			return
		# self.T1 = self.T1[-howMany:]
		# self.T1Ambient = self.T1Ambient[-howMany:]
		del self.T1[:-howMany]
		del self.T1Ambient[:-howMany]
		# self.T2 = self.T2[-howMany:]
		# self.T2Ambient = self.T2Ambient[-howMany:]
		del self.T2[:-howMany]
		del self.T2Ambient[:-howMany]
		# self.TimeStamp = self.TimeStamp[-howMany:]
		del self.TimeStamp[:-howMany]
		self.numEntries = howMany
	
	def saveTo(self,fid=None,format='csv'):
		if format == 'json':
			if fid is None:
				closeFile = True
				fname = 'Log_' + str(time()) + '.json'
				print('Saving log: {}'.format(fname))
				fid = open(fname,'w')
			else:
				closeFile = False
			saveDict = {'LogType':self.Title,'TimeStamp':self.TimeStamp[:],'T1':self.T1[:],
				'T1Ambient':self.T1Ambient[:],'T2':self.T2[:],'T2Ambient':self.T2Ambient[:]}
			json.dump(saveDict,fid)
			if closeFile:
				fid.close()
		else:
			if fid is None:
				fname = 'Log_' + str(time()) + '.csv'
				print('Saving log: {}'.format(fname))
				fid = open(fname,'w', newline='')
				closeFile = True
			else:
				closeFile = False
			try:
				writer = csv.writer(fid)
				writer.writerow(['Log Type','Time Stamp','T1','T2','T1 Ambient','T2 Ambient'])
				writer.writerow([self.Title])
				t = self.getTable()
				for ind in range(len(t)):
					writer.writerow([''] + t[ind])
				if closeFile:
					fid.close()
			except Exception as e:
				print(e)
				lastLogSaveName = 'failed'
			else:
				lastLogSaveName = fname
	
	def getDict(self):
		saveDict = {'TimeStamp':self.TimeStamp[:],'T1':self.T1[:],
			'T1Ambient':self.T1Ambient[:],'T2':self.T2[:],'T2Ambient':self.T2Ambient[:]}
		return {self.Title:saveDict}
	
	def load(self,logdict):
		if self.numEntries > 0:
			self.TimeStamp.clear()
			self.T1.clear()
			self.T1Ambient.clear()
			self.T2.clear()
			self.T2Ambient.clear()
		self.TimeStamp.extend(logdict['TimeStamp'])
		self.T1.extend(logdict['T1'])
		self.T1Ambient.extend(logdict['T1Ambient'])
		self.T2.extend(logdict['T2'])
		self.T2Ambient.extend(logdict['T2Ambient'])
		self.numEntries = len(self.TimeStamp)
	
	def getJSONBytes(self):
		saveDict = {'LogType':self.Title,'TimeStamp':self.TimeStamp[:],'T1':self.T1[:],
			'T1Ambient':self.T1Ambient[:],'T2':self.T2[:],'T2Ambient':self.T2Ambient[:]}
		return json.dumps(saveDict).encode()
	
	def getTable(self):
		ts = self.TimeStamp[:]
		t1 = self.T1[:]
		t1a = self.T1Ambient[:]
		t2 = self.T2[:]
		t2a = self.T2Ambient[:]
		t = []
		for ind in range(self.numEntries):
			t.append([ts[ind],t1[ind],t2[ind],t1a[ind],t2a[ind]])
			if ind % 1000 == 0:
				sleep(0)
		return t


def linearizeTemp(t,i):
	thermocoupleVoltage = (t - i) * 0.041276
	coldJunctionVoltage = (-0.176004136860E-01 +
		0.389212049750E-01  * i +
		0.185587700320E-04  * math.pow(i, 2.0) +
		-0.994575928740E-07 * math.pow(i, 3.0) +
		0.318409457190E-09  * math.pow(i, 4.0) +
		-0.560728448890E-12 * math.pow(i, 5.0) +
		0.560750590590E-15  * math.pow(i, 6.0) +
		-0.320207200030E-18 * math.pow(i, 7.0) +
		0.971511471520E-22  * math.pow(i, 8.0) +
		-0.121047212750E-25 * math.pow(i, 9.0) +
		0.118597600000E+00  * math.exp(-0.118343200000E-03 * math.pow((i-0.126968600000E+03), 2.0)))
	voltageSum = thermocoupleVoltage + coldJunctionVoltage
	if thermocoupleVoltage < 0:
		b0 = 0.0000000E+00
		b1 = 2.5173462E+01
		b2 = -1.1662878E+00
		b3 = -1.0833638E+00
		b4 = -8.9773540E-01
		b5 = -3.7342377E-01
		b6 = -8.6632643E-02
		b7 = -1.0450598E-02
		b8 = -5.1920577E-04
		b9 = 0.0000000E+00
	elif thermocoupleVoltage < 20.644:
		b0 = 0.000000E+00
		b1 = 2.508355E+01
		b2 = 7.860106E-02
		b3 = -2.503131E-01
		b4 = 8.315270E-02
		b5 = -1.228034E-02
		b6 = 9.804036E-04
		b7 = -4.413030E-05
		b8 = 1.057734E-06
		b9 = -1.052755E-08
	elif thermocoupleVoltage < 54.886:
		b0 = -1.318058E+02
		b1 = 4.830222E+01
		b2 = -1.646031E+00
		b3 = 5.464731E-02
		b4 = -9.650715E-04
		b5 = 8.802193E-06
		b6 = -3.110810E-08
		b7 = 0.000000E+00
		b8 = 0.000000E+00
		b9 = 0.000000E+00
	t = (b0 +
		b1 * voltageSum +
		b2 * pow(voltageSum, 2.0) +
		b3 * pow(voltageSum, 3.0) +
		b4 * pow(voltageSum, 4.0) +
		b5 * pow(voltageSum, 5.0) +
		b6 * pow(voltageSum, 6.0) +
		b7 * pow(voltageSum, 7.0) +
		b8 * pow(voltageSum, 8.0) +
		b9 * pow(voltageSum, 9.0))
	return t


def readAll():
	global T1, T2, state1, state2, linearizeTemps
	v = T1._read32()
	state1 = [(v & (1 << 0)) == 0,(v & (1 << 1)) == 0,(v & (1 << 2)) == 0,(v & (1 << 16)) == 0]
	if v & 0x7:
		t1 = float('NaN')
	else:
		t1 = v >> 18
		if v & 0x80000000:
			t1 -= 16384
		t1 = t1*0.25
	v >>= 4
	i1 = v & 0x7FF
	if v & 0x800:
		i1 -= 4096
	i1 *= 0.0625
	v = T2._read32()
	state2 = [(v & (1 << 0)) == 0,(v & (1 << 1)) == 0,(v & (1 << 2)) == 0,(v & (1 << 16)) == 0]
	if v & 0x7:
		# t2 = float('NaN')
		t2 = v >> 18
		if v & 0x80000000:
			t2 -= 16384
		t2 = t2*0.25
	else:
		t2 = v >> 18
		if v & 0x80000000:
			t2 -= 16384
		t2 = t2*0.25
	v >>= 4
	i2 = v & 0x7FF
	if v & 0x800:
		i2 -= 4096
	i2 *= 0.0625
	if linearizeTemps:
		pass
		# thermocoupleVoltage = (t1 - i1) * 0.041276
		# coldJunctionVoltage = (-0.176004136860E-01 +
			# 0.389212049750E-01  * i1 +
			# 0.185587700320E-04  * math.pow(i1, 2.0) +
			# -0.994575928740E-07 * math.pow(i1, 3.0) +
			# 0.318409457190E-09  * math.pow(i1, 4.0) +
			# -0.560728448890E-12 * math.pow(i1, 5.0) +
			# 0.560750590590E-15  * math.pow(i1, 6.0) +
			# -0.320207200030E-18 * math.pow(i1, 7.0) +
			# 0.971511471520E-22  * math.pow(i1, 8.0) +
			# -0.121047212750E-25 * math.pow(i1, 9.0) +
			# 0.118597600000E+00  * math.exp(-0.118343200000E-03 * math.pow((i1-0.126968600000E+03), 2.0)))
		# voltageSum = thermocoupleVoltage + coldJunctionVoltage
		# if thermocoupleVoltage < 0:
			# b0 = 0.0000000E+00
			# b1 = 2.5173462E+01
			# b2 = -1.1662878E+00
			# b3 = -1.0833638E+00
			# b4 = -8.9773540E-01
			# b5 = -3.7342377E-01
			# b6 = -8.6632643E-02
			# b7 = -1.0450598E-02
			# b8 = -5.1920577E-04
			# b9 = 0.0000000E+00
		# elif thermocoupleVoltage < 20.644:
			# b0 = 0.000000E+00
			# b1 = 2.508355E+01
			# b2 = 7.860106E-02
			# b3 = -2.503131E-01
			# b4 = 8.315270E-02
			# b5 = -1.228034E-02
			# b6 = 9.804036E-04
			# b7 = -4.413030E-05
			# b8 = 1.057734E-06
			# b9 = -1.052755E-08
		# elif thermocoupleVoltage < 54.886:
			# b0 = -1.318058E+02
			# b1 = 4.830222E+01
			# b2 = -1.646031E+00
			# b3 = 5.464731E-02
			# b4 = -9.650715E-04
			# b5 = 8.802193E-06
			# b6 = -3.110810E-08
			# b7 = 0.000000E+00
			# b8 = 0.000000E+00
			# b9 = 0.000000E+00
		# t1 = (b0 +
			# b1 * voltageSum +
			# b2 * pow(voltageSum, 2.0) +
			# b3 * pow(voltageSum, 3.0) +
			# b4 * pow(voltageSum, 4.0) +
			# b5 * pow(voltageSum, 5.0) +
			# b6 * pow(voltageSum, 6.0) +
			# b7 * pow(voltageSum, 7.0) +
			# b8 * pow(voltageSum, 8.0) +
			# b9 * pow(voltageSum, 9.0))
		# thermocoupleVoltage = (t2 - i2) * 0.041276
		# coldJunctionVoltage = (-0.176004136860E-01 +
			# 0.389212049750E-01  * i2 +
			# 0.185587700320E-04  * math.pow(i2, 2.0) +
			# -0.994575928740E-07 * math.pow(i2, 3.0) +
			# 0.318409457190E-09  * math.pow(i2, 4.0) +
			# -0.560728448890E-12 * math.pow(i2, 5.0) +
			# 0.560750590590E-15  * math.pow(i2, 6.0) +
			# -0.320207200030E-18 * math.pow(i2, 7.0) +
			# 0.971511471520E-22  * math.pow(i2, 8.0) +
			# -0.121047212750E-25 * math.pow(i2, 9.0) +
			# 0.118597600000E+00  * math.exp(-0.118343200000E-03 * math.pow((i2-0.126968600000E+03), 2.0)))
		# voltageSum = thermocoupleVoltage + coldJunctionVoltage
		# if thermocoupleVoltage < 0:
			# b0 = 0.0000000E+00
			# b1 = 2.5173462E+01
			# b2 = -1.1662878E+00
			# b3 = -1.0833638E+00
			# b4 = -8.9773540E-01
			# b5 = -3.7342377E-01
			# b6 = -8.6632643E-02
			# b7 = -1.0450598E-02
			# b8 = -5.1920577E-04
			# b9 = 0.0000000E+00
		# elif thermocoupleVoltage < 20.644:
			# b0 = 0.000000E+00
			# b1 = 2.508355E+01
			# b2 = 7.860106E-02
			# b3 = -2.503131E-01
			# b4 = 8.315270E-02
			# b5 = -1.228034E-02
			# b6 = 9.804036E-04
			# b7 = -4.413030E-05
			# b8 = 1.057734E-06
			# b9 = -1.052755E-08
		# elif thermocoupleVoltage < 54.886:
			# b0 = -1.318058E+02
			# b1 = 4.830222E+01
			# b2 = -1.646031E+00
			# b3 = 5.464731E-02
			# b4 = -9.650715E-04
			# b5 = 8.802193E-06
			# b6 = -3.110810E-08
			# b7 = 0.000000E+00
			# b8 = 0.000000E+00
			# b9 = 0.000000E+00
		# t2 = (b0 +
			# b1 * voltageSum +
			# b2 * pow(voltageSum, 2.0) +
			# b3 * pow(voltageSum, 3.0) +
			# b4 * pow(voltageSum, 4.0) +
			# b5 * pow(voltageSum, 5.0) +
			# b6 * pow(voltageSum, 6.0) +
			# b7 * pow(voltageSum, 7.0) +
			# b8 * pow(voltageSum, 8.0) +
			# b9 * pow(voltageSum, 9.0))
	return t1,i1,t2,i2


def emailLog(log=None):
	global lastLogSaveName, notification_email
	if log is None and lastLogSaveName is None:
		saveLogsCSV()
		if lastLogSaveName == 'failed':
			print('Email Failed - unable to save log')
			return
	msg = EmailMessage()
	msg['Subject'] = 'LN Monitor Log'
	msg['From'] = 'LN Monitor<robinsonlabiot@gmail.com>'
	msg['To'] = notification_email
	if log is None:
		ctype, encoding = mimetypes.guess_type(lastLogSaveName)
		if ctype is None or encoding is not None:
			ctype = 'application/octet-stream'
		maintype, subtype = ctype.split('/',1)
		print('Adding log attachment')
		with open(lastLogSaveName,'rb') as fid:
			msg.add_attachment(fid.read(),maintype=maintype,subtype=subtype,filename=lastLogSaveName)
	else:
		print('No Attachment')
	with smtplib.SMTP_SSL('smtp.gmail.com',465) as gmail:
		gmail.login('robinsonlabiot@gmail.com','brainlabGRB121')
		gmail.send_message(msg)


def saveLogsJSON(filename=None):
	global fastLog, minutesLog, hoursLog, daysLog, lastLogSaveName
	if filename is None:
		fname = 'Log_' + str(time()) + '.json'
	else:
		fname = filename + '.json'
	saveDict = dict()
	print('Saving log: {}'.format(fname))
	try:
		with open(fname,'w') as logfile:
			saveDict.update(fastLog.getDict())
			saveDict.update(minutesLog.getDict())
			saveDict.update(hoursLog.getDict())
			saveDict.update(daysLog.getDict())
			print(saveDict.keys())
			json.dump(saveDict,logfile)
	except Exception as e:
		print(e)
		lastLogSaveName = 'failed'
	else:
		lastLogSaveName = fname


def loadLogsJSON(filename=None):
	global fastLog, minutesLog, hoursLog, daysLog
	if filename is None:
		fname = 'LogDump.json'
	else:
		fname = filename + '.json'
	if not os.path.isfile(fname):
		print('No previous log found')
		return
	try:
		with open(fname) as f:
			saveDict = json.load(f)
	except json.decoder.JSONDecodeError as e:
		print('Previous Log File Empty')
		return
	fastLog.load(saveDict['SecondsX2'])
	minutesLog.load(saveDict['Minutes'])
	hoursLog.load(saveDict['Hours'])
	daysLog.load(saveDict['Days'])
	print('Loaded Previous Log')


def saveLogsCSV():
	global fastLog, minutesLog, hoursLog, daysLog, lastLogSaveName
	fname = 'Log_' + str(time()) + '.csv'
	print('Saving log: {}'.format(fname))
	try:
		with open(fname,'w', newline='') as logfile:
			writer = csv.writer(logfile)
			writer.writerow(['Log Type','Time Stamp','T1','T2','T1 Ambient','T2 Ambient'])
			writer.writerow(['Seconds x2'])
			t = fastLog.getTable()
			for ind in range(len(t)):
				writer.writerow([''] + t[ind])
			writer.writerow(['\t'])
			writer.writerow(['Log Type','Time Stamp','T1','T2','T1 Ambient','T2 Ambient'])
			writer.writerow(['Minutes'])
			t = minutesLog.getTable()
			for ind in range(len(t)):
				writer.writerow([''] + t[ind])
			writer.writerow(['\t'])
			writer.writerow(['Log Type','Time Stamp','T1','T2','T1 Ambient','T2 Ambient'])
			writer.writerow(['Hours'])
			t = hoursLog.getTable()
			for ind in range(len(t)):
				writer.writerow([''] + t[ind])
			writer.writerow(['\t'])
			writer.writerow(['Log Type','Time Stamp','T1','T2','T1 Ambient','T2 Ambient'])
			writer.writerow(['Days'])
			t = daysLog.getTable()
			for ind in range(len(t)):
				writer.writerow([''] + t[ind])
	except Exception as e:
		print(e)
		lastLogSaveName = 'failed'
	else:
		lastLogSaveName = fname


def savePlot(format='.png'):
	global fastLog, minutesLog, hoursLog, daysLog, lastLogSaveName
	fname = 'Log_' + str(time()) + format
	sys.stdout.write('Generating plot: {}\n'.format(fname))
	sys.stdout.flush()
	fig = plt.figure()
	fig.set_size_inches(32,8)
	fig.set_dpi(200)
	#print('Acquiring lock 1')
	#fastLog.lock.acquire()
	# ts = fastLog.TimeStamp[-7200:]
	# t1 = fastLog.T1[-7200:]
	# t1amb = fastLog.T1Ambient[-7200:]
	# t2 = fastLog.T2[-7200:]
	# t2amb = fastLog.T2Ambient[-7200:]
	# #fastLog.lock.release()
	# sleep(0)
	# if len(ts) > 0:
		# plt.subplot(2,4,1)
		# initTime = ts[0]
		# for ii in range(len(ts)):
			# ts[ii] -= initTime
		# plt.xlabel('Seconds since ' + strftime('%Y-%m-%d %H:%M:%S',localtime(initTime)))
		# plt.ylabel('Degrees C')
		# plt.plot(ts,t1amb,'r',ts,t2amb,'b')
		# sleep(0)
		# plt.subplot(2,4,5)
		# plt.xlabel('Seconds since ' + strftime('%Y-%m-%d %H:%M:%S',localtime(initTime)))
		# plt.ylabel('Degrees C')
		# plt.plot(ts,t1,'r',ts,t2,'b',)
		# plt.ylim(-200,ceil(max([max(t1),max(t2)])))
		# sleep(0)
	
	#print('Acquiring lock 2')
	# minutesLog.lock.acquire()
	ts = minutesLog.TimeStamp[:]
	t1 = minutesLog.T1[:]
	t1amb = minutesLog.T1Ambient[:]
	t2 = minutesLog.T2[:]
	t2amb = minutesLog.T2Ambient[:]
	# minutesLog.lock.release()
	sleep(0)
	if len(ts) > 0:
		# plt.subplot(2,4,2)
		plt.subplot(2,3,1)
		initTime = ts[0]
		for ii in range(len(ts)):
			ts[ii] = round((ts[ii] - initTime) / 60)
		plt.xlabel('Minutes since ' + strftime('%Y-%m-%d %H:%M',localtime(initTime)))
		plt.ylabel('Degrees C')
		plt.plot(ts,t1amb,'r',ts,t2amb,'b')
		sleep(0)
		# plt.subplot(2,4,6)
		plt.subplot(2,3,4)
		plt.xlabel('Minutes since ' + strftime('%Y-%m-%d %H:%M',localtime(initTime)))
		plt.ylabel('Degrees C')
		plt.plot(ts,t1,'r',ts,t2,'b',)
		plt.ylim(-200,ceil(max([max(t1),max(t2)])))
		sleep(0)
	
	#print('Acquiring lock 3')
	# hoursLog.lock.acquire()
	ts = hoursLog.TimeStamp[:]
	t1 = hoursLog.T1[:]
	t1amb = hoursLog.T1Ambient[:]
	t2 = hoursLog.T2[:]
	t2amb = hoursLog.T2Ambient[:]
	# hoursLog.lock.release()
	sleep(0)
	if len(ts) > 0:
		# plt.subplot(2,4,3)
		plt.subplot(2,3,2)
		initTime = ts[0]
		for ii in range(len(ts)):
			ts[ii] = round((ts[ii] - initTime) / 3600)
		plt.xlabel('Hours since ' + strftime('%Y-%m-%d %H:%M',localtime(initTime)))
		plt.ylabel('Degrees C')
		plt.plot(ts,t1amb,'r',ts,t2amb,'b')
		sleep(0)
		# plt.subplot(2,4,7)
		plt.subplot(2,3,5)
		plt.xlabel('Hours since ' + strftime('%Y-%m-%d %H:%M',localtime(initTime)))
		plt.ylabel('Degrees C')
		plt.plot(ts,t1,'r',ts,t2,'b',)
		plt.ylim(-200,ceil(max([max(t1),max(t2)])))
		sleep(0)
	
	#print('Acquiring lock 4')
	# daysLog.lock.acquire()
	ts = daysLog.TimeStamp[:]
	t1 = daysLog.T1[:]
	t1amb = daysLog.T1Ambient[:]
	t2 = daysLog.T2[:]
	t2amb = daysLog.T2Ambient[:]
	# daysLog.lock.release()
	sleep(0)
	if len(ts) > 0:
		# plt.subplot(2,4,4)
		plt.subplot(2,3,3)
		initTime = ts[0]
		for ii in range(len(ts)):
			ts[ii] = round((ts[ii] - initTime) / 43200)
		plt.xlabel('Days since ' + strftime('%Y-%m-%d',localtime(initTime)))
		plt.ylabel('Degrees C')
		plt.plot(ts,t1amb,'r',ts,t2amb,'b')
		sleep(0)
		# plt.subplot(2,4,8)
		plt.subplot(2,3,6)
		plt.xlabel('Days since ' + strftime('%Y-%m-%d',localtime(initTime)))
		plt.ylabel('Degrees C')
		plt.plot(ts,t1,'r',ts,t2,'b',)
		plt.ylim(-200,ceil(max([max(t1),max(t2)])))
		sleep(0)
	
	sys.stdout.write('Saving plot: {}'.format(fname))
	sys.stdout.flush()
	plt.savefig(fname, bbox_inches='tight')
	plt.close()
	lastLogSaveName = fname


def keyboardListener():
	global shuttingDown
	while not shuttingDown:
		entry = sys.stdin.readline()
		if not entry:
			break
		if entry.find('exit') > -1:
			shuttingDown = True
		elif entry.find('save') > -1:
			saveLogsCSV()


def ThermoRead():
	global temp1, temp2, inter1, inter2, counter, state1, state2, sendStatus, saveLog
	global fastLog, minutesLog, hoursLog, daysLog
	global levelAlarm, tempAlarm, shuttingDown
	
	fault = False
	
	temp1,inter1,temp2,inter2 = readAll()
	sleep(.1)
	for ii in range(9):
		t1,i1,t2,i2 = readAll()
		temp1+= t1
		inter1 += i1
		temp2 += t2
		inter2 += i2
		sleep(.1)
	
	temp1 /= 10
	inter1 /= 10
	temp2 /= 10
	inter2 /= 10
	
	while not shuttingDown and not fault:
		looptime = time()
		if temp1 == float('NaN'):
			temp1 = 0
		if temp2 == float('NaN'):
			temp2 = 0
		t1,i1,t2,i2 = readAll()
		if False in state1 + state2:
			print('Thermocouple Fault')
			fault = True
			continue
		temp1 = (9 * temp1 + t1) / 10
		inter1 = (inter1 * 9 + i1) / 10
		temp2 = (9 * temp2 + t2) / 10
		inter2= (inter2 * 9 + i2) / 10
		if counter % 5 == 0:
			fastLog.addTemp(linearizeTemp(temp1,inter1),inter1,linearizeTemp(temp2,inter2),inter2,looptime)
			if fastLog.numEntries % 120 == 0:
				minutesLog.addTemp(*fastLog.max(120))
				fastLog.keep_only(7200)
				if minutesLog.numEntries % 60 == 0:
					hoursLog.addTemp(*minutesLog.average(60))
					minutesLog.keep_only(1440)
					if abs(hoursLog.T1[-1] - hoursLog.T2[-1]) <= 1:
						pass
					if hoursLog.numEntries % 24 == 0:
						daysLog.addTemp(*hoursLog.average(24))
						hoursLog.keep_only(168)
						daysLog.keep_only(42)
						sys.stdout.write('Daily Save\n')
						sys.stdout.flush()
						saveLog = True
			newEntry.set()
		if counter == 0:
			sendStatus = True
		counter = (counter + 1) % 100
		sleep(max(looptime + 0.1 - time(),0.05))


if __name__ == '__main__':
	
	sys.stdout.write('Starting ThermoPi\n')
	sys.stdout.flush()
	
	# Set the notification email
	notification_email = 'm2j1q0m4v0k0n5x3@brainowls.slack.com'
	
	# Unlink / bind unix socket and listen for incoming connections
	try:
		os.unlink('./ThermoPi.pe')
	except OSError:
		if os.path.exists('./ThermoPi.pe'):
			raise
	serveSock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
	serveSock.bind('./ThermoPi.pe')
	serveSock.listen(10)
	
	# Set multiprocessing start method to forkserver to minimize overhead
	mp.set_start_method('forkserver')
	
	# Define globals for worker interactions
	newEntry = Event()
	sendStatus = True
	saveLog = False
	lastLogSaveName = None
	shuttingDown = False
	tempAlarm = False
	tempAlarmSent = False
	levelAlarm = False
	levelAlarmSent = False
	
	# Set term and int signals to be ignored - passed to child processes
	signal.signal(signal.SIGINT, signal.SIG_IGN)
	signal.signal(signal.SIGTERM, signal.SIG_IGN)
	
	# Import multiprocess functions <enforces simple context>
	import ThermoPiMP
	
	# Create Thermocouple reader objects
	CLK = 24
	SO = 10
	CS1 = 9
	CS2 = 11

	T1 = mx3.MAX31855(CLK,CS1,SO)   # Sensor 1, placed below the LN fill line
	T2 = mx3.MAX31855(CLK,CS2,SO) # Sensor 2, placed near the top plug
	
	# Define globals for current readings
	temp1 = 0
	inter1 = 0
	temp2 = 0
	inter2 = 0
	states = ['openCircuit','shortGND','shortVCC','fault']
	state1 = [True,True,True,True]
	state2 = [True,True,True,True]
	counter = 0
	linearizeTemps = True
	
	alarmCondition = 0
	
	# Initialize logs
	m = Manager()
	# sd = m.dict() # Shared Dict
	ll = dict()
	t1 = 'T1'
	t1a = 'T1Ambient'
	t2 = 'T2'
	t2a = 'T2Ambient'
	ts = 'TimeStamp'
	for log in ['fastLog','minutesLog','hoursLog','daysLog']:
		ll.update({log+t1:m.list(),log+t1a:m.list(),log+t2:m.list(),log+t2a:m.list(),log+ts:m.list()})
	log = 'fastLog'
	fastLog = TempLog('SecondsX2',ll[log+t1],ll[log+t1a],ll[log+t2],ll[log+t2a],ll[log+ts])
	log = 'minutesLog'
	minutesLog = TempLog('Minutes',ll[log+t1],ll[log+t1a],ll[log+t2],ll[log+t2a],ll[log+ts])
	log = 'hoursLog'
	hoursLog = TempLog('Hours',ll[log+t1],ll[log+t1a],ll[log+t2],ll[log+t2a],ll[log+ts])
	log = 'daysLog'
	daysLog = TempLog('Days',ll[log+t1],ll[log+t1a],ll[log+t2],ll[log+t2a],ll[log+ts])
	# fastLog = TempLog('SecondsX2')
	# minutesLog = TempLog('Minutes')
	# hoursLog = TempLog('Hours')
	# daysLog = TempLog('Days')
	
	# Term signal handler for systemd implementation
	termHandler = TermHandler()
	
	# Import & Initialize plotting module
	# import matplotlib
	# matplotlib.use('Agg')
	# from matplotlib import pyplot as plt
	
	# plt.ioff()
	
	# Load previous log
	loadLogsJSON()
	
	# Create and start keyboard listener thread worker
	keyListener = Thread(target=keyboardListener,daemon=True)
	keyListener.start()
	# Create and start thermocouple reader thread worker
	thermoReader = Thread(target=ThermoRead)
	thermoReader.start()
	
	# Create client list and worker variables
	clients = []
	emailer = None
	doEmail = False
	saver = None
	doSave = None
	
	try:
		while not shuttingDown:
			# while len(clients) == 0 and not shuttingDown:
				# r,w,e = select([serveSock],[],[],0.1)
				# for client in r:
					# newConn, addr = serveSock.accept()
					# clients.append(newConn)
					# sys.stdout.write('Client connected\n')
					# sys.stdout.flush()
					# sendStatus = True
				# if not thermoReader.is_alive() and not shuttingDown:
					# thermoReader.join(0.01)
					# thermoReader = Thread(target=ThermoRead)
					# thermoReader.start()
				# if termHandler.termSig:
					# shuttingDown = True
			r,w,e = select([serveSock],[],[],0)
			for client in r:
				newConn, addr = serveSock.accept()
				clients.append(newConn)
				sys.stdout.write('Client connected\n')
				sys.stdout.flush()
				sendStatus = True
			if not thermoReader.is_alive() and not shuttingDown:
				thermoReader.join(0.01)
				thermoReader = Thread(target=ThermoRead)
				thermoReader.start()
			if newEntry.is_set() and len(clients) > 0:
				t1 = linearizeTemp(temp1,inter1)
				t2 = linearizeTemp(temp2,inter2)
				for client in clients:
					try:
						client.sendall('T1: {0:.3f}  T2: {1:.3f}\a'.format(t1,t2).encode('utf-8'))
						if sendStatus:
							client.sendall('Ambient1: {0:.3f}  Ambient2: {1:.3f}\a'.format(inter1,inter2).encode('utf-8'))
							client.sendall('S1: {}, {}, {}, {}\a'.format(*state1).encode('utf-8'))
							client.sendall('S2: {}, {}, {}, {}\a'.format(*state2).encode('utf-8'))
					except Exception as e:
						sys.stdout.write('Client Send Failed\n')
						print(e)
						sys.stdout.flush()
						clients.remove(client)
				newEntry.clear()
				if sendStatus:
					sendStatus = False
				if saveLog:
					saveLog = False
					saver = Thread(target=saveLogsCSV)
					saver.start()
			sleep(0.01)
			r,w,e = select(clients,[],[],0)
			if r:
				for client in r:
					data = client.recv(32)
					if data:
						message = data.decode('utf-8')
						if message.startswith('stop'):
							shuttingDown = True
							continue
						elif message.startswith('save'):
							if doSave is None:
								if 'json' in message:
									doSave = 'json'
								else:
									doSave = 'csv'
						elif message.startswith('plot'):
							if doSave is None:
								doSave = 'plot'
						elif message.startswith('email'):
							doEmail = True
						elif message.startswith('linearize'):
							if 'off' in message:
								linearizeTemps = False
							else:
								linearizeTemps = True
						elif message.startswith('drop'):
							client.close()
							clients.remove(client)
							print('Client disconnected')
			if emailer is not None:
				if not emailer.is_alive():
					emailer.join(0.01)
					emailer = None
					sys.stdout.write('Email Sent\n')
					sys.stdout.flush()
			elif doEmail:
				if saver is None:
					doEmail = False
					sys.stdout.write('Sending email\n')
					sys.stdout.flush()
					emailer = Process(target=ThermoPiMP.emailFile,args=(lastLogSaveName,notification_email))
					# emailer = Thread(target=emailLog)
					emailer.start()
			if saver is not None:
				if not saver.is_alive():
					saver.join(0.01)
					saver = None
					sys.stdout.write('Log Saved\n')
					sys.stdout.flush()
			elif doSave is not None:
				if doSave == 'plot':
					doSave = None
					# saver = Thread(target=savePlot)
					fname = 'Log_' + str(time()) + '.png'
					lastLogSaveName = fname
					saver = Process(target=ThermoPiMP.savePlot,kwargs={'fname':fname,'d':ll})
					saver.start()
				elif doSave == 'json':
					doSave = None
					saver = Thread(target=saveLogsJSON)
					saver.start()
				elif doSave == 'csv':
					doSave = None
					saver = Thread(target=saveLogsCSV)
					saver.start()
			if termHandler.termSig:
				shuttingDown = True
	except Exception as e:
		print(e)
	finally:
		shuttingDown = True
		saveLogsJSON('LogDump')
		sleep(0.001)
		serveSock.close()
		os.unlink('./ThermoPi.pe')
		for client in clients:
			client.close()
		if emailer is not None:
			emailer.join(5)
		if saver is not None:
			saver.join(5)
		sleep(0.001)
		keyListener.join(1)
		thermoReader.join(1)
		if False in state1 + state2:
			exit(5)
		else:
			exit(0)
