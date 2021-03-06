
import multiprocessing
import os
import os.path
import sys
import traceback

from threading import Thread
from subprocess import *

if sys.hexversion < 0x03000000:
	import Queue
else:
	import queue as Queue

# Library locations
this_path = os.path.dirname(os.path.realpath(__file__))
libsvm_path = os.path.join(this_path, "..", "lib", "libsvm")
liblinear_path = os.path.join(this_path, "..", "lib", "liblinear")
crfsuite_path = os.path.join(this_path, "..", "lib", "crfsuite")

is_win32 = (sys.platform == 'win32')
if is_win32:
	libsvm_path = os.path.join(libsvm_path, "windows")
	liblinear_path = os.path.join(liblinear_path, "windows")
	crfsuite_path = os.path.join(crfsuite_path, "windows")
else:
	crfsuite_path = os.path.join(crfsuite_path, "frontend")

# File locations
svm_train = os.path.join(libsvm_path, "svm-train")
svm_predict = os.path.join(libsvm_path, "svm-predict")
lin_train = os.path.join(liblinear_path, "train")
lin_predict = os.path.join(liblinear_path, "predict")
crf_suite = os.path.join(crfsuite_path, "crfsuite")

# Parallel performance options
nr_local_worker = multiprocessing.cpu_count()

###############################################################################
# LIBSVM - cribbing largely from tools/grid.py and tools/easy.py
###############################################################################

def range_f(begin,end,step):
	# like range, but works on non-integer too
	seq = []
	while True:
		if step > 0 and begin > end: break
		if step < 0 and begin < end: break
		seq.append(begin)
		begin = begin + step
	return seq

def permute_sequence(seq):
	n = len(seq)
	if n <= 1: return seq

	mid = int(n/2)
	left = permute_sequence(seq[:mid])
	right = permute_sequence(seq[mid+1:])

	ret = [seq[mid]]
	while left or right:
		if left: ret.append(left.pop(0))
		if right: ret.append(right.pop(0))

	return ret

def redraw(db,best_param,tofile=False):
	if len(db) == 0: return
	begin_level = round(max(x[2] for x in db)) - 3
	step_size = 0.5

	best_log2c,best_log2g,best_rate = best_param

	# if newly obtained c, g, or cv values are the same,
	# then stop redrawing the contour.
	if all(x[0] == db[0][0]  for x in db): return
	if all(x[1] == db[0][1]  for x in db): return
	if all(x[2] == db[0][2]  for x in db): return

	if tofile:
		gnuplot.write(b"set term png transparent small linewidth 2 medium enhanced\n")
		gnuplot.write("set output \"{0}\"\n".format(png_filename.replace('\\','\\\\')).encode())
		#gnuplot.write(b"set term postscript color solid\n")
		#gnuplot.write("set output \"{0}.ps\"\n".format(dataset_title).encode().encode())
	elif is_win32:
		gnuplot.write(b"set term windows\n")
	else:
		gnuplot.write( b"set term x11\n")
	gnuplot.write(b"set xlabel \"log2(C)\"\n")
	gnuplot.write(b"set ylabel \"log2(gamma)\"\n")
	gnuplot.write("set xrange [{0}:{1}]\n".format(c_begin,c_end).encode())
	gnuplot.write("set yrange [{0}:{1}]\n".format(g_begin,g_end).encode())
	gnuplot.write(b"set contour\n")
	gnuplot.write("set cntrparam levels incremental {0},{1},100\n".format(begin_level,step_size).encode())
	gnuplot.write(b"unset surface\n")
	gnuplot.write(b"unset ztics\n")
	gnuplot.write(b"set view 0,0\n")
	gnuplot.write("set title \"{0}\"\n".format(dataset_title).encode())
	gnuplot.write(b"unset label\n")
	gnuplot.write("set label \"Best log2(C) = {0}  log2(gamma) = {1}  accuracy = {2}%\" \
				  at screen 0.5,0.85 center\n". \
				  format(best_log2c, best_log2g, best_rate).encode())
	gnuplot.write("set label \"C = {0}  gamma = {1}\""
				  " at screen 0.5,0.8 center\n".format(2**best_log2c, 2**best_log2g).encode())
	gnuplot.write(b"set key at screen 0.9,0.9\n")
	gnuplot.write(b"splot \"-\" with lines\n")
	


	
	db.sort(key = lambda x:(x[0], -x[1]))

	prevc = db[0][0]
	for line in db:
		if prevc != line[0]:
			gnuplot.write(b"\n")
			prevc = line[0]
		gnuplot.write("{0[0]} {0[1]} {0[2]}\n".format(line).encode())
	gnuplot.write(b"e\n")
	gnuplot.write(b"\n") # force gnuplot back to prompt when term set failure
	gnuplot.flush()


def calculate_jobs():
	c_seq = permute_sequence(range_f(c_begin,c_end,c_step))
	g_seq = permute_sequence(range_f(g_begin,g_end,g_step))
	nr_c = float(len(c_seq))
	nr_g = float(len(g_seq))
	i = 0
	j = 0
	jobs = []

	while i < nr_c or j < nr_g:
		if i/nr_c < j/nr_g:
			# increase C resolution
			line = []
			for k in range(0,j):
				line.append((c_seq[i],g_seq[k]))
			i = i + 1
			jobs.append(line)
		else:
			# increase g resolution
			line = []
			for k in range(0,i):
				line.append((c_seq[k],g_seq[j]))
			j = j + 1
			jobs.append(line)
	return jobs

class WorkerStopToken:  # used to notify the worker to stop
		pass

class Worker(Thread):
	def __init__(self,name,job_queue,result_queue):
		Thread.__init__(self)
		self.name = name
		self.job_queue = job_queue
		self.result_queue = result_queue
	def run(self):
		while True:
			(cexp,gexp) = self.job_queue.get()
			if cexp is WorkerStopToken:
				self.job_queue.put((cexp,gexp))
				# print('worker {0} stop.'.format(self.name))
				break
			try:
				rate = self.run_one(2.0**cexp,2.0**gexp)
				if rate is None: raise RuntimeError("get no rate")
			except:
				# we failed, let others do that and we just quit
			
				traceback.print_exception(sys.exc_info()[0], sys.exc_info()[1], sys.exc_info()[2])
				
				self.job_queue.put((cexp,gexp))
				print('worker {0} quit.'.format(self.name))
				break
			else:
				self.result_queue.put((self.name,cexp,gexp,rate))

class LocalWorker(Worker):
	def run_one(self,c,g):
		cmdline = '{0} -c {1} -g {2} -v {3} {4} {5}'.format \
		  (svmtrain_exe,c,g,fold,pass_through_string,dataset_pathname)
		result = Popen(cmdline,shell=True,stdout=PIPE).stdout
		for line in result.readlines():
			if str(line).find("Cross") != -1:
				return float(line.split()[-1][0:-1])

class SSHWorker(Worker):
	def __init__(self,name,job_queue,result_queue,host):
		Worker.__init__(self,name,job_queue,result_queue)
		self.host = host
		self.cwd = os.getcwd()
	def run_one(self,c,g):
		cmdline = 'ssh -x {0} "cd {1}; {2} -c {3} -g {4} -v {5} {6} {7}"'.format \
		  (self.host,self.cwd, \
		   svmtrain_exe,c,g,fold,pass_through_string,dataset_pathname)
		result = Popen(cmdline,shell=True,stdout=PIPE).stdout
		for line in result.readlines():
			if str(line).find("Cross") != -1:
				return float(line.split()[-1][0:-1])

class TelnetWorker(Worker):
	def __init__(self,name,job_queue,result_queue,host,username,password):
		Worker.__init__(self,name,job_queue,result_queue)
		self.host = host
		self.username = username
		self.password = password		
	def run(self):
		import telnetlib
		self.tn = tn = telnetlib.Telnet(self.host)
		tn.read_until("login: ")
		tn.write(self.username + "\n")
		tn.read_until("Password: ")
		tn.write(self.password + "\n")

		# XXX: how to know whether login is successful?
		tn.read_until(self.username)
		# 
		print('login ok', self.host)
		tn.write("cd "+os.getcwd()+"\n")
		Worker.run(self)
		tn.write("exit\n")			   
	def run_one(self,c,g):
		cmdline = '{0} -c {1} -g {2} -v {3} {4} {5}'.format \
		  (svmtrain_exe,c,g,fold,pass_through_string,dataset_pathname)
		result = self.tn.write(cmdline+'\n')
		(idx,matchm,output) = self.tn.expect(['Cross.*\n'])
		for line in output.split('\n'):
			if str(line).find("Cross") != -1:
				return float(line.split()[-1][0:-1])

def bits(n):
	while n:
		b = n & (~n+1)
		yield b
		n ^= b
		
###############################################################################
# Learning Interface
###############################################################################
LIN = 2**0
CRF = 2**1
SVM = 2**2
ALL = sum(2**i for i in range(3))

def train(model_filename, type=ALL):
	for t in bits(type):
		if t == SVM:
			filename = model_filename + ".svm"
			command = [svm_train, "-c", "50", "-g", "0.03", "-w0", "0.5", filename, filename + ".trained"]
		
		if t == LIN:
			filename = model_filename + ".lin"
			command = [lin_train, "-c", "50", "-w0", "0.5", filename, filename + ".trained"]
			
		if t == CRF:
			filename = model_filename + ".crf"
			command = [crf_suite, "learn", "-m", filename + ".trained", filename]
			
		output, error = Popen(command, stdout = PIPE, stderr = PIPE).communicate()
		#print output
		#print error
	
def predict(model_filename, type=ALL):
	for t in bits(type):
		if t == SVM:
			filename = model_filename + ".svm"
			command = [svm_predict, filename + ".test.in", filename + ".trained", filename + ".test.out"]
			
		if t == LIN:
			filename = model_filename + ".lin"
			command = [lin_predict, filename + ".test.in", filename + ".trained", filename + ".test.out"]
			
		if t == CRF:
			filename = model_filename + ".crf"
			command = [crf_suite, "tag", "-m", filename + ".trained" , filename + ".test.in"]	# NEEDS OUTPUT
			
		output, error = Popen(command, stdout = PIPE, stderr = PIPE).communicate()
		
		if t == CRF:
			with open(filename + ".test.out", "w") as f:
				for line in output.split():
					f.write(line + "\n")
		
def write_features(model_filename, rows, labels, type=ALL):
	for t in bits(type):
		if t == SVM:
			file_suffix = ".svm" + (".test.in" if not labels else "")
			null_label, feature_sep, sentence_sep = "-1", ":", ""
			
		if t == LIN:
			file_suffix = ".lin" + (".test.in" if not labels else "")
			null_label, feature_sep, sentence_sep = "-1", ":", ""
		
		if t == CRF:
			file_suffix = ".crf" + (".test.in" if not labels else "")
			null_label, feature_sep, sentence_sep = "", "=", "\n"

		filename = model_filename + file_suffix
		with open(filename, "w") as f:
			for sentence_index, sentence in enumerate(rows):
				if labels:
					sentence_labels = labels[sentence_index]
					assert "Dimension mismatch", len(sentence) == len(sentence_labels)

				for word_index, features in enumerate(sentence):
					if labels:
						label = sentence_labels[word_index]
						line = [str(label)]
					else:
						line = [null_label]

					for k,v in sorted(features.items()):
						line.append(str(k) + feature_sep + str(v))

					f.write("\t".join(line).strip() + "\n")
				
				f.write(sentence_sep)
				
def read_labels(model_filename, type=ALL):
	labels = {}
	for t in bits(type):
		if t == SVM:
			filename = model_filename + ".svm.test.out"
		
		if t == LIN:
			filename = model_filename + ".lin.test.out"
		
		if t == CRF:
			filename = model_filename + ".crf.test.out"
			
		with open(filename) as f:
			lines = f.readlines()
		labels[t] = [line.strip() for line in lines]
		
	return labels