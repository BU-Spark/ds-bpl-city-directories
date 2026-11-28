"""python build_records.py INPUT.csv OUTPUT.csv (Python 3.9+)"""
import argparse
import csv
import json
import re

NAME = r"[A-Z][a-zA-Z'’-]+"
DITTO = re.compile(r'^[«»“”"]+\s*(?=[A-Z])')
PERSON = re.compile(rf"^({NAME})\s+(?:{NAME}|[A-Z])\b")
BUSINESS = re.compile(r'\b(?:Co|Corp|Inc|Ltd|Company|Bros)\b|&')
ADDRESS = re.compile(r'^(?:rm\s+\d|(?:h|bds|res)\s+(?:at\b|\d)|warehouse\s+\d)')
FIELDS = 'page page_id source_url group joined_text record_text review_fragment source_lines raw_lines operations review_flags'.split()


ABBREVIATIONS = {'Alls': 'Allston',
 'Am': 'American',
 'Assn': 'Association',
 'B & A': 'Boston & Albany Railroad',
 'B & M': 'Boston & Maine Railroad',
 'B A A': 'Boston Athletic Association',
 'B E R': 'Boston Elevated Railway',
 'B F D': 'Boston Fire Department',
 'B F S Co': 'BF Sturtevant Co',
 'B P D': 'Boston Protective Department',
 'B S D & T Co': 'Boston Safe Deposit and Trust Co',
 'B S G Co': 'Bay State Gas Co',
 'B S H': 'Boston State Hospital',
 'B S I W & C Co': 'Bay State Insulated Wire & Cable Co',
 "B'line": 'Brookline',
 "B'way": 'Broadway',
 'B, R B & L': 'Boston, Revere Beach & Lynn Railroad',
 'Br': 'Brighton',
 'Bros': 'Brothers',
 'Camb': 'Cambridge',
 "Camb'pt": 'Cambridgeport',
 'Cen': 'Centre',
 'Chamb of Com': 'Chamber of Commerce',
 'Chsn': 'Charlestown',
 'Co': 'Company',
 "Com'l": 'Commercial',
 'Cong': 'Congregational',
 "Dev'shire": 'Devonshire',
 'Dor': 'Dorchester',
 'E': 'East',
 'E B': 'East Boston',
 'E B Co': 'East Boston Co',
 'E B T R R Co': 'East Boston Terminal Railroad Co',
 'E E I Co': 'Edison Electric Illuminationg Co',
 'Ex': 'Express',
 'F E': 'Fire Engine',
 'F H mkt': 'Faneuil Hall market',
 'F H sq': 'Faneuil Hall square',
 'Fairm': 'Fairmount',
 'Fen': 'Fenway',
 'G E Co': 'General Elctric CO',
 'H P': 'Hyde Park',
 'H T D': 'Hoosac Tunnel Docks',
 'Hlds': 'Highlands',
 'Hts': 'Heights',
 'Ins': 'Insurance',
 'Inst Tech': 'Mass Inst Tech',
 'J P': 'Jamaica Plain',
 'M & M T Co': 'Merchants & Miners Transportation Co',
 'Mass': 'Massachusetts',
 'Mat': 'Mattapan',
 'Met': 'Metropolitan',
 'Mfg': 'Manufacturing',
 'N': 'North',
 'N E Conservatory': 'New England Conservatory of Music',
 'N E T & T Co': 'New England Telephone & Telegraph Co',
 'N F H mkt': 'New Faneuil Hall market',
 'N Y & B D E Co': 'New York & Boston Despatch co',
 'N Y, N H & H': 'New York New Haven & Hartford Railroad',
 'Nep': 'Neponset',
 'P O sq': 'Post Office square',
 'Pemb sq': 'Pemberton square',
 'R M S': 'Railway Mail Service',
 'Readv': 'Readville',
 'Ros': 'Roslindale',
 'Rox': 'Roxbury',
 'S': 'South',
 'S B': 'South Boston',
 'Somv': 'Somerville',
 'U C': "Upham's Corner",
 'U S A': 'United States Army',
 'U S N': 'United States Navy',
 'W': 'West',
 'W R': 'West Roxbury',
 'Wash': 'Washington',
 'ab': 'above',
 'adv': 'advertising',
 'agt': 'agent',
 'al': 'alley',
 'apt': 'apartment',
 'asst': 'assistant',
 'aud': 'auditor',
 'av': 'avenue',
 'b': 'boards',
 'bds': 'boards',
 'bel': 'below',
 'bet': 'between',
 'bldg': 'building',
 'blk': 'block',
 'boul': 'boulevard',
 'c': 'corner',
 'clk': 'clerk',
 'coll': 'collection',
 'com': 'commission',
 'com mer': 'commission merchant',
 'com trav': 'commercial traveler',
 'cor': 'corner',
 'corp': 'corporation',
 'ct': 'court',
 'dep': 'deputy',
 'dept': 'department',
 'div': 'division',
 'do': 'ditto',
 'eng': 'engineer',
 'exch': 'exchange',
 'extn': 'extension',
 'fl': 'floor',
 'frt': 'freight',
 'h': 'house',
 'ins': 'insurance',
 'insp': 'inspector',
 'lab': 'laborer',
 'mech': 'mechanical',
 'mfg': 'manufacturing',
 'mfr': 'manufacturer',
 'mgr': 'manager',
 'mkr': 'maker',
 'mkt': 'market',
 'n': 'near',
 'opp': 'opposite',
 'opr': 'operator',
 'pass': 'passenger',
 'phone': 'telephone',
 'pl': 'place',
 'pres': 'president',
 'prof': 'professor',
 'prop': 'proprietor',
 'pub': 'publisher or publishing',
 'r': 'rear',
 'rd': 'road',
 'rem': 'removed',
 'rep': 'representative',
 'rm': 'room',
 'rms': 'rooms',
 'sec': 'secretary',
 'sect': 'section',
 'sol': 'solicitor',
 'sq': 'square',
 'st': 'street',
 'sta': 'station',
 'steno': 'stenographer',
 'supt': 'superintendent',
 'tel': 'telegraph',
 'ter': 'terrace',
 'treas': 'treasurer',
 'up': 'upper',
 'whf': 'wharf',
 'wid': 'widow'}
TOKEN = re.compile(r"(?<![\w’'])(" + "|".join(re.escape(k) for k in sorted(ABBREVIATIONS, key=len, reverse=True)) + r")(?![\w’'])")
PLACES = set("Alls Br Camb Cen Chsn Dor Fairm Fen Hlds Hts Mat Nep Readv Ros Rox Somv Wash Mass Met Ex Am".split()) | {"E B", "S B", "W R", "J P", "H P", "U C"}


def expand(text, flags):
    changes = []

    def replace(match):
        key = match[0]
        before, after = text[:match.start()], text[match.end():]
        address = re.search(r"\b(?:\d+[a-zA-Z]?|h|bds|rms|at)\b[^;()]{0,45}$", before)
        if key == 'do':
            flags.add('resolve_ditto_from_context')
            return key
        if key in {'E', 'W', 'N', 'S'}:
            if not re.search(r"\d+\s+$", before) or not re.match(r"\s+[A-Z][a-z]", after):
                return key
        elif key in PLACES and not address:
            return key
        elif len(key) == 1 and not re.match(r"\s+(?:\d|at\b|do\b)", after):
            flags.add('check_short_abbreviation')
            return key
        changes.append(key)
        return ABBREVIATIONS[key]

    return TOKEN.sub(replace, text), changes


import math

MODEL = {'district': {'bias': -0.9578267340645965,
              'coef': [5.422964853985327,
                       -0.03557223223271927,
                       -0.6692382506342298,
                       0.40302859536651336,
                       -0.2819957662528582,
                       0.09415161632338896]},
 'join': {'bias': -2.3970789151020546,
          'coef': [0.4528039734726972,
                   0.8804216965607223,
                   0.7695181636785278,
                   2.389174524033737,
                   0.6323399536931102,
                   2.0981837543971356,
                   -1.257303634961557,
                   1.0103314668292356,
                   -0.7483157086117548]}}


def boundary(left, right):
    a, b = left.split(), right.split()
    if not a or not b:
        return [0] * 9
    return [left.endswith('-'), a[-1].isdigit(), a[-1] in {'at','h','rm','bds','and'},
            b[0][0].islower(), b[0][0].isdigit(), len(b) <= 4,
            b[0][0] in '«»"“', len(a) >= 8, bool(re.search(r'\b(h|bds|rms)\s',right))]


def district(text):
    words = text.rstrip('.,;').split()
    if len(words) < 2:
        return [0] * 6
    tail = words[-1]
    return [tail.istitle(), len(tail) <= 4, words[-2].istitle(),
            words[-2].lower() in {'rd','av','st','sq','pl','ct','ter','pk'},
            any(w.isdigit() for w in words[-6:-1]), 'at' in words[-3:-1]]


def predict(features, weights):
    score = weights['bias'] + sum(x*y for x,y in zip(features, weights['coef']))
    return 1 / (1 + math.exp(-score))



def flag_place(record, weights):
    line = record['record_text']
    if line and re.search(r'\b(?:h|bds|rms)\b.*\d', line):
        tail = line.rstrip('.,;').split()[-1]
        if (re.fullmatch(r"[A-Z][a-z]{1,6}", tail) and tail not in ABBREVIATIONS
                and tail not in ABBREVIATIONS.values() and predict(district(line), weights['district']) >= .8):
            record['review_flags'].add('check_possible_place:' + tail)
    return record


MARK = re.compile(r"""^[«»“”"‘’]+\s*""")
STREET_END = re.compile(r"\b(?:av|rd|st|sq|pl|pk|ter|Dor|Rox|Chsn|Br|Alls|S B|E B)\b")

def plausible_heading(text):
    return (bool(re.fullmatch(r"[A-Z][a-z'’-]{2,}", text))
            and text not in ABBREVIATIONS and text not in ABBREVIATIONS.values())

def build(rows):
    weights = MODEL
    previous_group = None
    group_line = 0
    surname = ''
    current = None
    for number, row in enumerate(rows, 1):
        raw = next(row[key] for key in ('text', 'tesseract_text', 'raw_line') if key in row)
        url = row.get('source_page_url') or row.get('sources', '')
        match = re.search(r'/page/([^/]+)', url)
        page = row.get('printed_page') or (match.group(1) if match else '')
        page_id = row.get('page_id') or url or page
        if not page_id and 'raw_line' not in row:
            raise ValueError(f'Missing page identity at input row {number}')
        block = row.get('block_num', '')
        column = row.get('column', '')
        group = (page_id, column, block)
        line = ' '.join(raw.split())
        source = row.get('line_id') or row.get('') or str(number)
        flags = set()
        if not page_id:
            flags.add('page_unknown')
        if not column and not block:
            flags.add('layout_unverified')
        auxiliary = row.get('line_scope') in {'reference_or_margin', 'supplementary_unreviewed'}
        same = current and previous_group == group and not auxiliary and current['record_text'] and 'outside_body' not in current['review_flags']
        group_line = group_line + 1 if previous_group == group else 1
        if same and line and not MARK.match(line) and 'possible_surname_heading' not in current['review_flags']:
            prior = current['record_text']
            join_word = re.search(r'[A-Za-z]-$', prior) and re.match(r'^[a-z]', line)
            address = ADDRESS.match(line) or (re.search(r'\b(?:bds|rm|h|res)$', prior) and re.match(r'^\d+\s+[A-Z]', line))
            score = predict(boundary(current['raw_lines'][-1].strip(), line), weights['join']) if page_id else 0
            if .45 <= score < .8 and not (join_word or address):
                flags.add('possible_continuation')
            # A directional street continuation may share its OCR line with a
            # bracket fragment. Keep the fragment visible and flag its attachment for review.
            street_part = line.split('[', 1)[0].strip()
            directional_tail = (page_id and surname and '[' in line
                                and re.search(r'\b(?:bds|h|rms)\s+\d+$', prior)
                                and re.fullmatch(r'[EWNS] [A-Z][a-z]+', street_part))
            if directional_tail:
                current['record_text'] += ' ' + line
                current['raw_lines'].append(raw)
                current['source_lines'].append(source)
                current['operations'].append('join_directional_address')
                current['review_flags'].update(('inferred_join', 'check_bracket_attachment'))
                continue
            if (join_word or address or score >= .8) and '[' not in line and '[' not in prior:
                current['record_text'] = prior[:-1] + line if join_word else prior + ' ' + line
                current['source_lines'].append(source)
                current['raw_lines'].append(raw)
                current['operations'].append('join_hyphen' if join_word else ('join_address' if address else 'ml_join'))
                current['review_flags'].add('inferred_join')
                continue
        if current:
            yield flag_place(current, weights)
        if previous_group != group:
            surname = ''
        previous_group = group
        operations = []
        if auxiliary or not line:
            surname = ''
            flags.add('outside_body' if auxiliary else 'empty_ocr')
        elif MARK.match(line):
            body = MARK.sub('', line, count=1)
            if not body:
                line = ''
                flags.add('detached_ditto_mark')
                surname = ''
            elif surname and re.match(r'[A-Z&]', body) and not body.startswith('See '):
                line = surname + ' ' + body
                operations.append('expand_surname')
                flags.add('inferred_surname')
            else:
                # Preserve the exact glyph in raw_lines. Never invent a name.
                line = body
                flags.add('unknown_surname' if not body.startswith('See ') else 'cross_reference')
        elif group_line <= 4 and plausible_heading(line):
            surname = line
            flags.add('possible_surname_heading')
        else:
            prior_line = current['raw_lines'][-1].strip() if same else ''
            short_address = (len(line.split()) <= 8 and STREET_END.search(line)
                             and (re.search(r'\b(?:h|bds|at|rms|\d+)$', prior_line)
                                  or line in PLACES or re.match(r'^[EWNS]\s', line)))
            if short_address and surname:
                flags.add('possible_address_continuation')
            else:
                person = PERSON.match(line)
                surname = person[1] if person and not BUSINESS.search(line.split('(')[0]) else ''
                if not surname and not BUSINESS.search(line):
                    flags.add('uncertain_start')
        if '[' in line or ']' in line or re.search(r'\bdo\b', line):
            flags.add('check_context')
        current = dict(page=page, page_id=page_id, source_url=url, group=column or block,
                       record_text=line, source_lines=[source], raw_lines=[raw],
                       operations=operations, review_flags=flags)
    if current:
        yield flag_place(current, weights)


def unmatched_marks(text):
    partners = {')': '(', ']': '[', '}': '{'}
    stacks = {k: [] for k in partners.values()}
    unmatched = []
    for i, ch in enumerate(text):
        if ch in stacks:
            stacks[ch].append(i)
        elif ch in partners:
            opened = stacks[partners[ch]]
            if opened:
                opened.pop()
            else:
                unmatched.append(i)
    return sorted(unmatched + [i for stack in stacks.values() for i in stack])


def clean_symbols(text, flags):
    invalid = unmatched_marks(text)
    split = next((i for i in invalid if text[i] == '['), len(text))
    fragment = text[split + 1:].strip()
    if split < len(text):
        flags.add('check_fragment_owner')
    invalid = set(invalid)
    body = ''.join((' ' if i in invalid else ch) for i, ch in enumerate(text[:split]))
    if invalid:
        flags.add('unmatched_delimiter')
    body, count = re.subn(r'[=|_\\~]+', ' ', body)
    if count:
        flags.add('ocr_symbol_noise')
    body = ' '.join(body.split())
    if body and not any(ch.isalnum() for ch in body):
        flags.add('symbols_only')
        body = ''
    return body, fragment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input')
    parser.add_argument('output')
    args = parser.parse_args()
    from pathlib import Path
    if Path(args.input).resolve() == Path(args.output).resolve():
        parser.error('Choose an output path different from the input')
    with open(args.input, encoding='utf-8-sig', newline='') as src, open(args.output, 'w', encoding='utf-8-sig', newline='') as dst:
        writer = csv.DictWriter(dst, FIELDS)
        writer.writeheader()
        for record in build(csv.DictReader(src)):
            flags = record['review_flags']
            if record['record_text'].endswith('-'):
                flags.add('open_hyphen')
            record['joined_text'] = record['record_text']
            body, record['review_fragment'] = clean_symbols(record['joined_text'], flags)
            record['record_text'], changes = expand(body, flags)
            record['operations'].extend('expand:' + key for key in changes)
            record['review_flags'] = '|'.join(sorted(flags))
            for key in ('raw_lines', 'source_lines', 'operations'):
                record[key] = json.dumps(record[key], ensure_ascii=False)
            writer.writerow(record)


if __name__ == '__main__':
    main()
