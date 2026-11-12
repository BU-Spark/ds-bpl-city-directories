"""Validate the checked-in search snapshot. Python stdlib only."""
import collections,csv,hashlib,json,pathlib
root=pathlib.Path(__file__).resolve().parents[1];p=root/'data'
people=json.loads((p/'people.json').read_text());audit=json.loads((p/'unresolved_and_nonperson.json').read_text());rows=json.loads((p/'source_ocr_lines.json').read_text());byid={r['id']:r for r in rows}
for stem in ['people','unresolved_and_nonperson','source_ocr_lines']:
    js=json.loads((p/(stem+'.json')).read_text())
    with (p/(stem+'.csv')).open(encoding='utf-8-sig',newline='') as f: cs=list(csv.DictReader(f))
    assert len(js)==len(cs)
    for a,b in zip(js,cs):
        for k,v in a.items():
            expected=json.dumps(v,ensure_ascii=False) if isinstance(v,(list,dict)) else '' if v is None else str(v)
            assert b[k]==expected,(stem,k)
for model,key in [('Tesseract','t'),('DOTS.MOCR','m')]:
    records=[r for r in people+audit if r['ocr_model']==model]
    assert collections.Counter(r['source_line_ids'][0] for r in records)==collections.Counter(byid.keys())
    for r in records:
        assert r['original_ocr_text']=='\n'.join(byid[i][key] for i in r['source_line_ids'])
        assert all(byid[i]['page']==r['source_page'] for i in r['source_line_ids'])
        assert r['latitude'] is None and r['longitude'] is None
        if r['home_address']: assert r['residence_marker'] in ['h','bds','rms']
        if 'surname_context_without_ditto_requires_review' in r['flags']: assert r['name'] is None
source=(root/'site/ocr.html').read_bytes()
assert hashlib.sha256(source).hexdigest()==json.loads((p/'validation.json').read_text())['source_sha256']
for stem in ['people.csv','people.json']:
    assert (p/stem).read_bytes()==(root/'site/files'/stem).read_bytes()
assert len(rows)==1573 and len(people)==1922
print('PASS: CSV/JSON equivalence, source-model coverage, verbatim provenance, unchanged OCR HTML, website data consistency and null coordinates.')
