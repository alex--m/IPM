import os
from ctypes import *
from ctypes import util

MAX_PATH_LEN = 1000

class UCXTuner(object):
	def __init__(self, tuning_path=None):
		pipe_type = POINTER(c_int * 2)
		self._libucs = cdll.LoadLibrary(util.find_library('ucs'))
		self._libc = cdll.LoadLibrary(util.find_library('c'))
		
		if not tuning_path:
			tuning_path = os.environ['UCX_TUNING_PATH']
		
		def UCS_STATUS(value):
			if value != 0:
				raise Exception("UCX returned error #%i" % value)
			return value
	
		self._libucs.ucs_tune_open_cmd.argtypes = [pipe_type, c_char_p]
		self._libucs.ucs_tune_open_cmd.restype = UCS_STATUS
		
		self._libucs.ucs_tune_send_cmd_enum_ctxs.argtypes = [pipe_type, POINTER(c_char_p)]
		self._libucs.ucs_tune_send_cmd_enum_ctxs.restype = UCS_STATUS
		
		self._libucs.ucs_tune_send_cmd_set_param.argtypes = [pipe_type, c_char_p, c_char_p]
		self._libucs.ucs_tune_send_cmd_set_param.restype = UCS_STATUS
		
		self._libucs.ucs_tune_send_cmd_get_param.argtypes = [pipe_type, c_char_p, POINTER(c_char_p)]
		self._libucs.ucs_tune_send_cmd_get_param.restype = UCS_STATUS
		
		self._libc.free.argtypes = [c_void_p]
		
		self._pipe = pointer((c_int * 2)())
		self._libucs.ucs_tune_open_cmd(self._pipe,
			create_string_buffer(tuning_path))

	def enum_contexts(self):
		assert(self._pipe)
		contexts = c_char_p()
		self._libucs.ucs_tune_send_cmd_enum_ctxs(self._pipe, byref(contexts))
		ret = str(contexts.value)
		self._libc.free(contexts)
		return ret

	def __setitem__(self, key, value):
		assert(self._pipe)
		self._libucs.ucs_tune_send_cmd_set_param(self._pipe,
												 create_string_buffer(key),
												 create_string_buffer(str(value)))

	def __getitem__(self, key):
		assert(self._pipe)
		value = c_char_p()
		self._libucs.ucs_tune_send_cmd_get_param(self._pipe,
												 create_string_buffer(key),
												 byref(value))
		ret = str(value.value).strip()
		if ret.endswith("k"):
			ret = int(ret[:-1])*1024
		elif ret.endswith("m"):
			ret = int(ret[:-1])*1024*1024
		elif ret.endswith("g"):
			ret = int(ret[:-1])*1024*1024*1024
		self._libc.free(value)
		return ret

	def close(self):
		assert(self._pipe)
		os.close(self._pipe[0])
		os.close(self._pipe[1])
		self._pipe = None







def tuner(s):
	return {
		"RNDV_THRESHOLD": 1000,
		"ZCOPY_THRESHOLD": 100,
		"c": 3000,
		"d": 4000
	}[s]

def retune(s,x,T):
	print("#%i set %s to %d" % (os.getpid(),s,x))
	T[s] = x

class par(object):
	def __init__(self, name, val, default):
		self.val = val
		self.default = default
		self.name = name
		self.step = default
		self.state = 0
		self.bottom = 0
		self.up = 0
		self.direc = 0
		self.N = 0
		self.mean = 0
	def __str__(self):
		return ("name = %s, ini = %d, default = %d" % (self.name, self.val, self.default))

class CBER(object):
	def __init__(self, pars):
		self.tuner = UCXTuner()
		self.pars = []
		for i in range(0,len(pars)):
			x = tuner(pars[i])
			self.pars.append(par(pars[i] , x , x))
			retune(self.pars[i].name, x, self.tuner)

		self.cur = 0
		self.num = len(pars)
		self.score = -1
	def show(self):
		for p in self.pars:
			print(p)
			
	def reboot(self):
		cur = self.cur
		self.pars[cur].num = self.pars[cur].num + 1
		n = self.pars[cur].num
		self.pars[cur].mean = (self.pars[cur].mean * (n-1) + self.pars[cur].val)/n
		self.pars[cur].state = 0

	
	def update(self, score):
		prev = self.score
		self.score = score
		cur = self.cur

		if (self.pars[cur].state == 0):
			self.fast_increase(prev,score, cur)
		elif (self.pars[cur].state == 1):
			self.slow_search(prev,score, cur)

		return self.pars[cur].val

	def fast_increase(self,prev,score,cur):
		if (prev == -1):
			self.try_higher(cur)
		elif (prev < score):
			self.pars[cur].bottom = self.pars[cur].val
			self.try_higher(cur)
		else:
			self.pars[cur].up = self.pars[cur].val
			self.pars[cur].state =1
			self.pars[cur].val = (self.pars[cur].up + self.pars[cur].bottom) / 2
			self.pars[cur].step = (self.pars[cur].up - self.pars[cur].bottom) / 4
			self.pars[cur].direc = -1
			retune(self.pars[cur].name, self.pars[cur].val, self.tuner)

	def slow_search(self,prev,score,cur):
		if ((self.pars[cur].direc == 1 and prev < score) or (self.pars[cur].direc == -1 and prev > score)):
			self.pars[cur].val+= self.pars[cur].step
			self.pars[cur].direc = 1
		else:
			self.pars[cur].val-= self.pars[cur].step
			self.pars[cur].direc = -1

		self.pars[cur].step = max(self.pars[cur].step/2,20)
		retune(self.pars[cur].name, self.pars[cur].val, self.tuner)


	def try_higher(self, idx):
		self.pars[idx].val = self.pars[idx].val * 2
		retune(self.pars[idx].name, self.pars[idx].val, self.tuner)

	def next(self):
		self.cur = self.cur + 1
		if (self.cur == self.num):
			self.cur = 0

"""
if __name__ == "__main__":
	cber = CBER(["UCX_ZCOPY_THRESHOLD"])
	x = 100
	for i in range(0,20):
		L = -pow(x-1200,2)
		x = cber.update(L)
"""









my_id = None
cber = None
last_counts = {}
last_sums = {}

def ipm_mpi_callback(id, count, interval_sum, interval_last):
	global last_counts, last_sums, my_id, cber
	
	if my_id == None:
		my_id = id
	elif my_id != id:
		return
	
	last_count = last_counts.get(id, 0)
	last_counts[id] = count
	count -= last_count

	last_sum = last_sums.get(id, 0)
	last_sums[id] = interval_sum
	interval_sum -= last_sum

	if cber == None:
		cber = CBER(["ZCOPY_THRESHOLD"])
	try:
		print "Avg. over the last %i calls (of type %i) was %f (last measurement was %f)" % (count, id, float(interval_sum) / count, interval_last)
		#zcopy_thresh = cber.tuner["ZCOPY_THRESH"]
		#if zcopy_thresh:
		#	cber.tuner["ZCOPY_THRESH"] = int(zcopy_thresh) + 1
		#cber.update(-interval_sum)
	except Exception,e:
		print e

