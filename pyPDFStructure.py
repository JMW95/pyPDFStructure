# pyPDFStructure
# by Jamie Wood
# v0.1 May 2015
# requires zlib and re
#
# Example Usage:
# fin = open("mydoc.pdf", "rb")
# doc = PDFDocument(fin.read())
#
# Use PDFDocument.get_structure_tree() to get the top-level Structure element.
# The rest of the tree may be accessed by using a tree-search on each element's
# .kids list.
# Leaf elements will be instances of MarkedContent, and will have a .text field
# containing the actual text displayed at that location in the structure tree.
#
# Note this is only designed to work with Tagged PDFs, e.g those exported by
# Word 2010 and later, which contain structual information for accessibility,
# none of which is retained by other python pdf libraries, but which is crucial
# to automatic data extraction from PDFs
#
#
# This library will do nothing with PDFs which do not contain structure data.
#
#

# Basic method I used to build PDF structure:
#
# find trailer and get: pos of xref table and xrefstm, and index of root object
#  decode xrefstm and read xreftable and build map of objects to locations
#  load root object and get: pages object index, structuretreeroot object index
#  load pages object and get: list of page object indices
#   load each page object and get: contents object index
#    load contents object and store all MCs in global dict of MCs
#  load structuretreeroot object and build document tree recursively

import re
import zlib

def print_dict(d, indent=""): # helper method to pretty-print dicts
	for k in d:
		v = d[k]
		if type(v) == dict:
			print indent + k
			print_dict(v, indent + " ")
		elif type(v) == list:
			print indent + k
			for itm in v:
				print indent + " " + str(itm)
		else:
			print indent + k + ": " + str(v)

def int_from_bytes(bs): # used to convert bytes in xrefstm to ints
	bs = bytearray(bs)
	bs.reverse()
	res = 0
	for x in range(len(bs)-1, -1, -1):
		res += bs[x]
		if x != 0:
			res = res << 8
	return res

def get_reference(str):
	parts = str.strip(" \n\r").split(" ") # str is like "123 0 R"
	if len(parts)<3:
		raise Exception("Tried to dereference non-reference: " + str)
	return int(parts[0])

def is_alpha(c):
	o = ord(c)
	return (o >= ord("A") and o <= ord("Z")) or (o >= ord("a") and
		o <= ord("z")) or (o >= ord("0") and o <= ord("9"))

def read_dict(str): # parse a dictionary including nested arrays and dicts
	str = str.strip(" \n\r")
	i=0
	done = False
	indict = False
	inkey = False
	invalue = False
	waiting = "key"
	currkeyname = ""
	currvalue = ""
	lastchar = ""
	d = {}
	while i < len(str) and not done:
		c = str[i]
		if indict: # if we are in a dictionary
			
			if not invalue and not inkey:
				if waiting=="key" and c=="/":
					inkey = True
				elif waiting=="value" and c!=" ":
					invalue = True
			
			if inkey: # if we are currently reading a key name
				if is_alpha(c): # if we are still reading value key-name chars
					currkeyname += c # append to the current key name
				elif len(currkeyname)>0: # reached end of key
					inkey = False
					while str[i] in ['\n', '\r', ' ']:
						i += 1
					c = str[i]
					if str[i:i+2]=="<<": # if value is a dict, read recursively
						(d[currkeyname], offset) = read_dict(str[i:])
						currkeyname = ""
						currvalue = ""
						waiting = "key" # get ready to read another key
						i += (offset-1) # skip to the end of the dict
					elif str[i]=="[": # if value is an array
						(d[currkeyname], offset) = read_array(str[i:]) # read it
						currkeyname = ""
						currvalue = ""
						waiting = "key" # get ready to read another key
						i += (offset-1) # skip to the end of the array
					elif c==" ":
						waiting = "value"
					else:
						invalue = True
			
			if invalue: # if we are currently reading a value
				if (c != "/" and c!=">") or len(currvalue)==0:
					currvalue += c # most chars are ok
				else:
					if currkeyname != "": # if we actually read a key
						d[currkeyname] = currvalue.strip(" \n\r") # store it
					currkeyname = ""
					currvalue = ""
					invalue = False
					inkey = True
			
			if c==">" and lastchar==">": # reached end of dict
				done = True
		else:
			if c=="<" and lastchar=="<": # found start of dict
				indict = True
		lastchar = c
		i += 1
	return (d, i) # return the dict and number of chars consumed

def read_array(str): # TODO: method is hideous, need to write a proper parser
	out = []
	end = str.find("]")+1
	str = str[:end]
	refs = re.findall("\[*\s*(\d+\s+\d+\s+R)", str)
	if len(refs)>0: # if it was an array of references
		for ref in refs:
			out.append(ref)
	else:
		vals = re.findall("\[*/([^/\]]+)", str)
		if len(vals)>0: # if it was an array of strings
			for val in vals:
				out.append(val)
		else:
			hexs = re.findall("\[*(<\w+>)", str)
			if len(hexs)>0: # if it was an array of hex values
				for hex in hexs:
					out.append(hex)
			else:
				vals = re.findall("\[*\W*(\d+?)\W", str)
				if len(vals)>0: # if it was an array of ints
					for val in vals:
						out.append(int(val))
	return (out, end) # return array and number of chars consumed

def do_load_object(doc, str, forcetype=None):
	# we have forcetype to allow reading of objects which do not declare a type,
	# but we know what type they must be (eg content streams, info object)
	(d, dict_end) = read_dict(str) # read the object dictionary
	str = str[dict_end:].strip(" \n\r")
	if "Type" in d:
		type = d["Type"]
	else:
		type = forcetype
	
	if type != None:
		o = None
		if type=="/ObjStm": # Object Stream
			o = ObjStm(doc, str, d)
		elif type=="/Catalog": # Catalog
			o = Catalog(doc, d)
		elif type=="/Pages": # Pages object
			o = Pages(doc, d)
		elif type=="/Page": # Page object
			o = Page(doc, d)
		elif type=="/Font": # Font object
			o = Font(doc, str, d)
		elif type=="/CMap": # Character Map object
			o = CMap(doc, str, d)
		elif type=="/StructTreeRoot": # Root of Structure Tree
			o = StructTreeRoot(doc, d)
		elif type=="/StructElem": # Element of Structure Tree
			o = StructElem(doc, d)
		elif type=="/ContentStm": # Page Contents (needs to be forced)
			o = ContentStm(doc, str, d)
		elif type=="/Info": # PDF Info dict (needs to be forced):
			o = PDFInfo(d)
		elif type=="/OBJR": # PDF Object (image etc. - should be safe to ignore)
			print "OBJR found, ignoring"
			o = None
		else:
			raise Exception("Unknown type: " + type)
	else:
		raise Exception("Object does not declare a type, and none was forced.")
	return o

class MarkedContent: # a marked piece of text (linked somewhere in structure)
	def __init__(self, doc, str):
		self.text = ""
		lines = str.split("\n")
		currfont = None
		for line in lines:
			line = line.strip(" \t\n\r")
			if len(line)<2:
				continue
			if line[-2:]=="Tf":
				currfont = doc.currentpage.fonts[line.split(" ")[0].strip("/")]
			if line[-2:]=="TJ":
				escape = False
				inbracket = False
				inunicode = False
				unicodetmp = ""
				for ch in line[:-2].strip(" []"):
					if escape:
						self.text += ch
						escape = False
					else:
						if not inunicode:
							if ch=="(":
								inbracket = True
								continue
							elif ch==")":
								inbracket = False
								continue
						if not inbracket:
							if ch=="<":
								inunicode = True
								continue
							elif ch==">":
								inunicode = False
								continue
						if ch=="\\":
							escape=True
						else:
							if inbracket:
								self.text += ch
							elif inunicode:
								unicodetmp += ch
							if len(unicodetmp)==4:
								self.text += unichr(currfont.tounicode.map_char(int(unicodetmp, 16)))
								unicodetmp = ""
								
class PDFObj: # parent class for all PDF objects
	def __init__(self, doc, type):
		self.doc = doc
		self.type = type

class Catalog(PDFObj): # the root of the document, contains pages and structure
	def __init__(self, doc, d):
		PDFObj.__init__(self, doc, "Catalog")
		self.pages = doc.get_object(get_reference(d["Pages"]))
		if "StructTreeRoot" in d:
			self.structtreeroot = doc.get_object(get_reference(d["StructTreeRoot"]))

class Pages(PDFObj): # the 'pages' object, containing a list of all pages
	def __init__(self, doc, d):
		PDFObj.__init__(self, doc, "Pages")
		self.count = int(d["Count"])
		self.pages = []
		for pageref in d["Kids"]:
			self.pages.append(doc.get_object(get_reference(pageref)))

class Page(PDFObj): # a single page, contains the content stream with text etc.
	def __init__(self, doc, d):
		PDFObj.__init__(self, doc, "Page")
		fontrefs = d["Resources"]["Font"]
		self.fonts = {}
		for k in fontrefs:
			self.fonts[k] = doc.get_object(get_reference(fontrefs[k]))
		doc.currentpage = self # store the current page so font lookups can be made
		self.contents = doc.get_object(
			get_reference(d["Contents"]), "/ContentStm" )

class Font(PDFObj): # a font object
	def __init__(self, doc, str, d):
		PDFObj.__init__(self, doc, "Font")
		try:
			self.tounicode = doc.get_object(get_reference(d["ToUnicode"]), "/CMap")
		except KeyError:
			pass

class CMap(PDFObj): # a character map object
	def read_charcode(self, line, start):
		start = line.find("<", start)+1
		end = line.find(">", start)
		return int(line[start:end], 16), end
	
	def map_char(self, charcode):
		for mapping in self.mappings:
			if mapping[0] <= charcode and mapping[1] >= charcode:
				return mapping[2] + (charcode - mapping[0])
	
	def __init__(self, doc, str, d):
		PDFObj.__init__(self, doc, "CMap")
		startstream = str.find("stream")+6
		endstream = str.rfind("endstream")
		# we need to remove the newlines:
		# if using UNIX newlines, remove 1 char, else remove 2 (Windows newlines)
		startstream += 2 if str[startstream] == '\r' else 1
		endstream -= 2 if str[endstream-1] == '\r' else 1
		stmdata = str[startstream:endstream]
		if d["Filter"]=="/FlateDecode": # if the filter is zlib/decompress
			dec = zlib.decompress(stmdata) # then decode the stream data
		else:
			raise Exception("Unknown stream format: " + d["Filter"])
		self.mappings = []
		reading_char = False
		reading_range = False
		for line in dec.split("\n"):
			line = line.strip(" \r\n")
			if line[-11:] == "beginbfchar":
				reading_char = True
			elif line[-9:] == "endbfchar":
				reading_char = False
			elif line[-12:] == "beginbfrange":
				reading_range = True
			elif line[-10:] == "endbfrange":
				reading_range = False
			else:
				if reading_char:
					src, adv = self.read_charcode(line, 0)
					dst, _ = self.read_charcode(line, adv)
					self.mappings.append([src, src, dst])
				elif reading_range:
					base, e1 = self.read_charcode(line, 0)
					end, e2 = self.read_charcode(line, e1)
					dst, _ = self.read_charcode(line, e2)
					self.mappings.append([base, end, dst])

class ContentStm(PDFObj): # a content stream, with rendering command / text
	def get_mc(self, id):
		id = int(id)
		if id in self.mcs:
			return self.mcs[id]
		else:
			print self.mcs
			raise Exception("Cannot find MCID " + str(id))
	
	def __init__(self, doc, str, d):
		PDFObj.__init__(self, doc, "ContentStm")
		startstream = str.find("stream")+6
		endstream = str.rfind("endstream")
		# we need to remove the newlines:
		# if using UNIX newlines, remove 1 char, else remove 2 (Windows newlines)
		startstream += 2 if str[startstream] == '\r' else 1
		endstream -= 2 if str[endstream-1] == '\r' else 1
		stmdata = str[startstream:endstream]
		if d["Filter"]=="/FlateDecode": # if the filter is zlib/decompress
			dec = zlib.decompress(stmdata) # then decode the stream data
		else:
			raise Exception("Unknown stream format: " + d["Filter"])
		self.mcs = {} # keep a dict of all marked content
		offset = 0
		while True:
			start = dec.find("<</MCID", offset) # find marked content
			if start<0:
				break
			next = dec.find("<</MCID ", start+10)
			end_of_dict = dec.find(">>", start)
			end = dec.rfind("EMC", start, next)
			
			(d, _) = read_dict(dec[start:end_of_dict+2]) # read the MC dict
			id = int(d["MCID"]) # get the id
			
			self.mcs[id] = MarkedContent(doc, dec[start:end]) # store in our dict
			offset = end # skip to the end of this MC

class StructTreeRoot(PDFObj): # the root of the structure tree
	def __init__(self, doc, d):
		PDFObj.__init__(self, doc, "StructTreeRoot")
		self.kids = []
		for ref in d["K"]:
			self.kids.append(doc.get_object(get_reference(ref)))

class StructElem(PDFObj): # an element in the structure tree, may be one of many
	# subtypes, such as P (paragraph), Sect (document section) etc.
	def __init__(self, doc, d):
		PDFObj.__init__(self, doc, "StructElem")
		self.subtype = d["S"]
		self.kids = []
		
		if "Pg" in d:
			self.page = doc.get_object(get_reference(d["Pg"]))
		
		if type(d["K"])!=list: # hotfix for times when K is present as a string
			d["K"] = [int(d["K"])]
		
		for ref in d["K"]:
			if type(ref)==str:
				self.kids.append(doc.get_object(get_reference(ref)))
			else:
				self.kids.append(self.page.contents.get_mc(ref))
			
class ObjStm(PDFObj): # object stream containing compressed PDF objects
	def __init__(self, doc, str, di):
		PDFObj.__init__(self, doc, "ObjStm")
		
		self.xreftable = {}
		self.objects = {}
		
		startstream = str.find("stream")+6
		endstream = str.rfind("endstream")
		# we need to remove the newlines:
		# if using UNIX newlines, remove 1 char, else remove 2 (Windows newlines)
		startstream += 2 if str[startstream] == '\r' else 1
		endstream -= 2 if str[endstream-1] == '\r' else 1
		str = str[startstream:endstream]
		if di["Filter"]=="/FlateDecode":
			dec = zlib.decompress(str) # decompress it
			self.dec = dec
		else:
			raise Exception("Unknown stream format: " + di["Filter"])
		
		first_offset = int(di["First"]) # jump to first object position
		
		id_offsets = dec[:first_offset].replace('\n', " ").replace('\r', "").split(" ") # remove newlines from the id list
		i = 0
		while i < len(id_offsets)-1: # last element is garbage
			id = int(id_offsets[i]) # get the id
			offset = int(id_offsets[i+1]) + first_offset # calculate the offset
			self.xreftable[id] = offset # store in the xref-table
			i += 2
	
	def load_object(self, id, offset, forcetype=None):
		end = self.dec.rfind("\n", offset)
		str = self.dec[offset:end]
		o = do_load_object(self.doc, str, forcetype) # load the object
		self.objects[id] = o # store the new object for lookup later
		return o
	
	def get_object(self, ref, forcetype=None):
		if ref in self.objects: # if we've already loaded the object
			return self.objects[ref]
		if ref in self.xreftable: # if we know where to load it from
			return self.load_object(ref, self.xreftable[ref], forcetype)
		raise Exception("Don't know how to find object " + str(ref) +
			" in object stream!")

class PDFInfo: # the information about the PDF document
	def __init__(self, d):
		self.author = d["Author"]
		self.creator = d["Creator"]
		self.creationdate = d["CreationDate"]
		self.moddate = d["ModDate"]
		self.producer = d["Producer"]
			
class PDFDocument: # the main class for the document
	def get_structure_tree(self):
		if hasattr(self.rootnode, 'structtreeroot'):
			return self.rootnode.structtreeroot
		else:
			print("PDF file does not contain structure information!")
	
	def load_object(self, id, offset, forcetype=None):
		str = self.pdfdoc[offset:]
		start = str.find("obj")+3 # find start and end point of this object
		end = str.find("endobj")
		str = str[start:end].strip(" \n\r")
		o = do_load_object(self, str, forcetype) # load the object
		self.objects[id] = o # store the new object for lookup later
		return o
	
	def get_object(self, ref, forcetype=None):
		if ref in self.objects: # if object is loaded
			return self.objects[ref] # return it
		if ref in self.xrefstm: # if object is listed in a xref-stream
			objstm = self.get_object(self.xrefstm[ref]) # find the stream
			return objstm.get_object(ref, forcetype) # use it to get the object
		if ref in self.xreftable: # if we know where to find it
			return self.load_object(
				ref, self.xreftable[ref], forcetype) # load the object
		raise Exception("Don't know how to find object " + str(ref) + "!")
	
	def read_xref_table(self, str):
		start_idx_count = str.find("\n")+1 # find first newline (after "xref")
		end_idcnt = str.find("\n", start_idx_count) # find newline after
		idcnt_text = str[start_idx_count:end_idcnt].strip(" \n\r")
		parts = idcnt_text.split(" ") # split the index/count
		first_idx = int(parts[0])
		idx_count = int(parts[1])
		offset = end_idcnt+1 # byte offset for end of current line
		for x in range(first_idx, first_idx+idx_count, 1):
			end_offset = str.find("\n", offset)+1 # find end of line
			fields = str[offset:end_offset].split(" ") # split the fields
			if fields[2][0]=="n": # if the object is in use ("n", not "f")
				self.xreftable[x] = int(fields[0]) # add its offset to the table
			offset = end_offset
	
	def read_xref_stm(self, str):
		start = str.find("stream")+6 # find the position of the stream data
		(d, dict_end) = read_dict(str[:start]) # read dict
		end = str.find("endstream")
		stmdata = str[start:end].strip(" \n\r") # cut it out
		
		if d["Filter"]=="/FlateDecode": # if the filter is zlib/decompress
			dec = zlib.decompress(stmdata) # then decode the stream data
		else:
			raise Exception("Unknown stream format: " + d["Filter"])
		first_idx = 0
		if "Index" in d:
			first_idx = d["Index"][0]
		wids = d["W"] # read the field widths from dict
		wtype = wids[0] # width of type field
		wloc = wids[1] # width of location field
		wgen = wids[2] # width of generation number field
		record_width = sum(wids) # get the total width of each record in bytes
		offset = 0
		id = first_idx
		while offset<len(dec):
			byt = dec[offset:offset+record_width] # get current record
			typ = int_from_bytes(byt[0:wtype])
			loc = int_from_bytes(byt[wtype:wtype+wloc])
			gen = int_from_bytes(byt[wtype+wloc:])
			
			if typ==1: # if type is non-compressed
				self.xreftable[id] = loc # store it in the usual xref-table
			elif typ==2: # if type is compressed
				# loc is obj number of obj stream
				# gen is index in obj stream -> not needed
				self.xrefstm[id] = loc
			offset += record_width
			id += 1
		
		# get the root object
		self.rootnode = self.get_object(get_reference(d["Root"]))
		# get the info object
		self.info = self.get_object(get_reference(d["Info"]), "/Info")
	
	def read_trailer(self, str):
		(d, dict_end) = read_dict(str) # read the dict
		self.objectcount = int(d["Size"]) # get the total number of objects
		if "ID" in d: # if trailer has a document id
			self.documentid = d["ID"]
		if "XRefStm" in d: # if trailer has a cross-reference stream
			self.read_xref_stm(self.pdfdoc[int(d["XRefStm"]):])
		if "Prev" in d: # if trailer has a previous cross-reference table
			self.read_xref_table(self.pdfdoc[int(d["Prev"]):])
		
		# get the root object
		self.rootnode = self.get_object(get_reference(d["Root"]))
		# get the info object
		self.info = self.get_object(get_reference(d["Info"]), "/Info")
	
	def __init__(self, str):
		str = str.rstrip() # remove any extra newlines from the end of the file
		self.pdfdoc = str # store the full text, used for byte-offsets
		self.objects = {}
		self.xreftable = {}
		self.xrefstm = {}
		
		# find pos of xref table
		end_xref_offset = str.rfind("\n") # after xref-offset
		end_startxref = str.rfind("\n", 0, end_xref_offset) # before xref-offset
		# read the byte offset of xref-table
		str_xref = str[end_startxref:end_xref_offset]
		startxref_offset = int(str_xref.strip(" \n\r"))
		if str[startxref_offset:startxref_offset+4] == "xref":
			self.read_xref_table(str[startxref_offset:]) # read the table
		else:
			self.read_xref_stm(str[startxref_offset:])
		
		# read trailer
		end_of_objs = str.rfind("endobj")
		start_trailer = str.rfind("trailer",end_of_objs) # find the trailer, if it exists
		if start_trailer >= 0:
			start_trailer_dict = str.find("<<", start_trailer) # find trailer dict
			end_trailer_dict = str.find(">>", start_trailer_dict)+2
			# process the trailer
			self.read_trailer(str[start_trailer_dict:end_trailer_dict])


# TEST STUFF BELOW
# HERE BE DRAGONS
		
#fin = open("CaffDinner.pdf", "rb")
#s = fin.read()
#fin.close()

#doc = PDFDocument(s)

#fout = open("tree.txt", "wb")
#def dfs(fout, elem, indent=""):
#	if isinstance(elem, StructElem):
#		fout.write(indent + elem.subtype + "\n")
#	else:
#		fout.write(indent + elem.type + "\n")
#	
#	for k in elem.kids:
#		if isinstance(k, StructElem):
#			dfs(fout, k, indent + "--")
#		elif isinstance(k, MarkedContent):
#			fout.write(indent + "--" + k.text + "\n")
#		elif k is None:
#			fout.write(indent + "--" + "<<OBJECT>>" + "\n")
#		else:
#			fout.write(indent + "--" + "<<UNKNOWN>>" + "\n")

#dfs(fout, doc.get_structure_tree())
#fout.close()