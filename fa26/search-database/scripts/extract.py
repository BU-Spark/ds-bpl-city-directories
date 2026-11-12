"""Conservative, model-specific extraction from the supplied static HTML. Stdlib only."""
import argparse, collections, csv, hashlib, json, pathlib, re, shutil

def norm(s): return re.sub(r'\s+', ' ', s).strip()
def dump(p,x): p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
RES=re.compile(r'\b(h|bds|rms)\b(?=\s|$)')
DITTO=re.compile(r'^[\s"“”«»\u0027]+')
BUS=re.compile(r'\b(?:Co|Company|Corp|Society|Association|Bank|Church)\b|&')
OCC=re.compile(r'\b(?:clerk|salesman|laborer|carpenter|machinist|driver|teamster|tailor|bookkeeper|stenographer|teacher|nurse|lawyer|physician|jeweler|shoemaker|grocer|pedler|porter|cook|waiter|painter|plumber|engineer|conductor|watchman|polisher|cigarmaker|mgr|pres|treas|sec|asst|agt|com trav|tel opr|student|widow|Mrs|Miss|removed|died)\b')
EXPANSIONS={'av':'avenue','sq':'square','rd':'road','pk':'park','ct':'court','pl':'place','rm':'room','whf':'wharf','Wash':'Washington','B\'way':'Broadway','StBotolph':'Saint Botolph','Dor':'Dorchester','Rox':'Roxbury','Chsn':'Charlestown','Alls':'Allston','Somv':'Somerville','Camb':'Cambridge',"B'line":'Brookline'}

def expand(s):
 if not s:return None
 for a,b in sorted(EXPANSIONS.items(),key=lambda t:-len(t[0])):
  s=re.sub(r'(?<!\w)'+re.escape(a)+r'(?!\w)',b,s)
 for a,b in [('S B','South Boston'),('E B','East Boston'),('J P','Jamaica Plain'),('H P','Hyde Park'),('W R','West Roxbury')]:s=re.sub(r'\b'+a+r'\b',b,s)
 return s

def extract(rows,key):
 out=[]; surname=None; surname_line=None;page=None
 for i,row in enumerate(rows):
  raw=row[key]; text=norm(raw); flags=[]
  if row['page']!=page: surname=None;surname_line=None;page=row['page']
  clean=DITTO.sub('',text).strip(); ditto=clean!=text
  # A heading is evidence for the following surname, not itself a person.
  heading=bool(re.fullmatch(r'A[a-zA-Z\u0027-]{2,}',clean))
  if heading:surname=clean;surname_line=row['id']
  lead=re.match(r'^(A[a-d][a-zA-Z\u0027-]*)\s+([A-Z])',clean)
  if lead:surname=lead[1];surname_line=row['id']
  marks=list(RES.finditer(clean))
  prefix=clean[:marks[0].start()] if marks else clean
  outside=re.sub(r'\([^)]*\)','',prefix)
  business=bool(BUS.search(outside))
  person=bool(clean and re.match(r'^[A-Z]',clean) and not heading and not business and (marks or OCC.search(clean)))
  kind='person_candidate' if person else ('business_or_organization' if business else ('surname_heading' if heading else 'unresolved_text'))
  record={'record_id':f'{key}-{row["id"]:04d}','record_type':kind,'source_page':row['page'],'source_url':row['url'],'source_line_ids':[row['id']],'ocr_model':'Tesseract' if key=='t' else 'DOTS.MOCR','original_ocr_text':raw,'name':None,'name_as_printed':None,'surname_context_line_id':None,'surname_context_candidate':None,'occupation':None,'affiliation_or_relationship':None,'work_address':None,'home_address':None,'residence_marker':None,'work_address_geocoding':None,'home_address_geocoding':None,'address_for_geocoding':None,'geocoding_address_type':None,'geocoding_status':'not_prepared','latitude':None,'longitude':None,'flags':flags,'review_required':True}
  other=row['m' if key=='t' else 't']
  if norm(other)!=text:flags.append('ocr_models_differ_on_source_line')
  if not person:
   flags.append('not_parsed_as_person');out.append(record);continue
  # Join at most two immediately adjacent fragments with clear continuation cues.
  parts=[clean]
  for following in rows[i+1:i+3]:
   if following['page']!=page:break
   frag=norm(following[key]); prev=parts[-1]
   if not frag or DITTO.match(frag) or OCC.search(frag):break
   continuation=bool(re.match(r'^(?:\d|[a-z])',frag))
   continuation=continuation or bool(re.search(r'(?:-|\b(?:h|bds|rms|at|E|W|S|N)|\b\d+)$',prev) and re.match(r'^[A-Z]',frag))
   if not continuation or BUS.search(frag):break
   parts.append(frag);record['source_line_ids'].append(following['id'])
  combined=' '.join(parts)
  if len(parts)>1:
   flags.append('continuation_join_requires_review')
   combined=re.sub(r'(?<=[A-Za-z])- (?=[a-z])','',combined)
   record['original_ocr_text']='\n'.join(rows[j-1][key] for j in record['source_line_ids'])
  merged_markers = len(RES.findall(combined)) > 1
  # Bracket fragments often originate in another column; never silently assign them.
  if '[' in combined:
   flags.append('bracketed_fragment_unassigned');flags.append('address_context_possibly_interleaved');combined=combined.split('[',1)[0].strip()
  if re.search(r'\bdo\b',combined):flags.append('ditto_address_unresolved')
  if re.search(r'\b(?:removed|died)\b',combined):flags.append('historical_status_not_current_address')
  if merged_markers:
   flags.append('multiple_residence_markers_possible_merged_entries');out.append(record);continue
  # Name ends at first occupation, affiliation, number, or residence marker.
  cut=re.search(r'\(|\d|\b(?:h|bds|rms)\b|\b[a-z][a-z\u0027-]*\b|\b(?:Mrs|Miss)\b',combined)
  name=combined[:cut.start()].strip(' ,.;:') if cut else ''
  if not name or not re.fullmatch(r"[A-Za-z .\u0027-]+",name):
   flags.append('name_uncertain_or_missing');out.append(record);continue
  record['name_as_printed']=name
  if lead:record['name']=name
  elif surname:
   record['surname_context_line_id']=surname_line
   if ditto:
    record['name']=surname+' '+name;flags.append('surname_expanded_from_context')
   else:
    record['name']=None;record['surname_context_candidate']=surname;flags.append('surname_context_without_ditto_requires_review')
  else:
   record['name']=None;flags.append('surname_missing_or_uncertain')
  rest=combined[len(name):].strip(' ,.;:')
  marker=RES.search(rest)
  before=rest[:marker.start()].strip() if marker else rest
  home=rest[marker.end():].strip() if marker else None
  if marker:record['residence_marker']=marker[1]
  # Parenthetical affiliation is separate from occupation.
  affiliation=re.match(r'^\(([^)]*)\)\s*',before)
  if affiliation:record['affiliation_or_relationship']=affiliation[1];before=before[affiliation.end():]
  if re.match(r'^(?:widow|Mrs|Miss)\b',before):
   record['affiliation_or_relationship']=before;before='';flags.append('occupation_not_stated_relationship_only')
  address=re.search(r'\b\d+[A-Za-z]?\b',before)
  occ=before[:address.start()].strip(' ,;') if address else before.strip(' ,;')
  work=before[address.start():].strip() if address else None
  # Do not turn cross-references or status notices into occupational data.
  if re.search(r'\b(?:see|removed|died)\b',occ,re.I):occ=None;work=None
  record['occupation']=occ or None
  if occ and not re.search(r'[a-z]{2}',occ):record['occupation']=None;flags.append('occupation_unreadable')
  for field,value in [('work_address',work),('home_address',home)]:
   if value and re.search(r'\bdo\b',value):
    flags.append(field+'_ditto_unresolved');value=None
   if value and re.fullmatch(r'(?:at\s+)?\d*',value):
    flags.append(field+'_incomplete');value=None
   if value and (value.endswith('-') or re.search(r'\b(?:at|E|W|N|S)$',value)):
    flags.append(field+'_possibly_truncated')
   if value and re.search(r'[^\w\s\u0027.,&()/-]',value):flags.append(field+'_ocr_noise')
   record[field]=value or None
   if not value:flags.append(field+'_missing_or_uncertain')
  if not record['occupation']:flags.append('occupation_missing_or_uncertain')
  if not marker:flags.append('home_address_no_explicit_residence_marker')
  if work:flags.append('work_address_inferred_from_position_before_residence')
  for field in ['work_address','home_address']:
   val=record[field]
   if val and not any(f.startswith(field+'_') and any(k in f for k in ['truncated','noise','incomplete','unresolved']) for f in flags):
    record[field+'_geocoding']=expand(re.sub(r'^at\s+','',val))
  addr=record['home_address_geocoding'] or record['work_address_geocoding']
  if addr:
   record['address_for_geocoding']=addr
   record['geocoding_address_type']='home' if record['home_address_geocoding'] else 'work'
   record['geocoding_status']='needs_historical_address_review'
   flags.append('geocoding_locality_not_assumed')
  flags.append('unverified_ocr_extraction')
  out.append(record)
 return out

def csvwrite(path,rows):
 with path.open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader()
  for r in rows:w.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(list,dict)) else v for k,v in r.items()})

def main():
 ap=argparse.ArgumentParser();ap.add_argument('html',type=pathlib.Path);ap.add_argument('output',type=pathlib.Path);a=ap.parse_args();a.output.mkdir(parents=True,exist_ok=True)
 raw=a.html.read_bytes();s=raw.decode('utf-8');rows=json.loads(re.search(r'<script[^>]*id="dataset"[^>]*>(.*?)</script>',s,re.S)[1])
 records=extract(rows,'t')+extract(rows,'m');people=[r for r in records if r['record_type']=='person_candidate'];audit=[r for r in records if r['record_type']!='person_candidate']
 for name,data in [('people',people),('unresolved_and_nonperson',audit)]:dump(a.output/(name+'.json'),data);csvwrite(a.output/(name+'.csv'),data)
 dump(a.output/'source_ocr_lines.json',rows);csvwrite(a.output/'source_ocr_lines.csv',rows)
 shutil.copyfile(a.html,a.output/'index.html')
 summary={'source_sha256':hashlib.sha256(raw).hexdigest(),'website_unchanged':raw==(a.output/'index.html').read_bytes(),'source_lines':len(rows),'pages':sorted(set(r['page'] for r in rows)),'person_candidates_by_model':dict(collections.Counter(r['ocr_model'] for r in people)),'candidate_records_not_unique_people':len(people),'audit_records':len(audit),'all_source_model_lines_accounted_for':len(records)==2*len(rows),'flags':dict(collections.Counter(f for r in people for f in r['flags']))}
 dump(a.output/'validation.json',summary);dump(a.output/'abbreviations.json',{'residence_markers':{'h':'home/residence','bds':'boards; residential address','rms':'rooms; residential address'},'geocoding_expansions':EXPANSIONS,'occupation_glossary':{'mgr':'manager','pres':'president','treas':'treasurer','sec':'secretary','asst':'assistant','agt':'agent','com trav':'commercial traveler','tel opr':'telephone operator'},'unresolved':{'do':'ditto; no automatic address copying','Br':'ambiguous locality; retained','rm':'room; kept as address detail'}})
 print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
