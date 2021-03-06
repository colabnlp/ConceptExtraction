from __future__ import with_statement

class Note:
	def __init__(self, txt, con=None):
		self.sents = []
		with open(txt) as f:
			for line in f:
				self.sents.append([[w, "none"] for w in line.split()])
				
		if con:
			with open(con) as f:
				for line in f:
					c, t = line.split('||')
					t = t[3:-2]
					c = c.split()
					start = c[-2].split(':')
					end = c[-1].split(':')
					assert "concept spans one line", start[0] == end[0]
					l = int(start[0]) - 1
					start = int(start[1])
					end = int(end[1])
					
					for i in range(start, end + 1):
						self.sents[l][i][1] = t

	def __iter__(self):
		return iter(self.sents)
		
def read_txt(txt):
	note = []
	with open(txt) as f:
		for line in f:
			note.append([w for w in line.split()])
	return note		
	
def read_con(con, txt):
	label = [['none'] * len(line) for line in txt]
	with open(con) as f:
		for line in f:
			c, t = line.split('||')
			t = t[3:-2]
			c = c.split()
			start = c[-2].split(':')
			end = c[-1].split(':')
			assert "concept spans one line", start[0] == end[0]
			l = int(start[0]) - 1
			start = int(start[1])
			end = int(end[1])
			
			for i in range(start, end + 1):
				label[l][i] = t
	return label
		
def write_con(con, data, labels):
	with open(con, 'w') as f:
		for i, tmp in enumerate(zip(data, labels)):
			datum, label = tmp
			for j, tmp in enumerate(zip(datum, label)):
				datum, label = tmp
				if label != 'none':
					idx = "%d:%d" % (i + 1, j)
					print >>f, "c=\"%s\" %s %s||t=\"%s\"" % (datum, idx, idx, label)