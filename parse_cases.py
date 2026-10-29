"""Turns GenAI_Platform_Case_Set_A-H.pdf into static/cases.json. Run: python parse_cases.py <pdf>"""
import json, re, sys, pdfplumber
SEC={'Story':'story','Opening lines':'opening','Clock':'clock','Pressure without a clock':'pressure','Findings':'vitals0','Vitals on arrival':'vitals',
 'Examination, released on request':'exam','Test results, released only if ordered':'results','AI panel':'ai','Likely diagnoses':'dx','Suggested questions':'sq',
 'Suggested tests now':'tests','Related tests':'related','Suggested medicines':'meds','Cautions':'cautions','Simulated reference data (invented for the platform)':'sim',
 'Reference management (hidden, for scoring)':'ref','Questions the doctor should ask':'dq','Questions the patient or attendant asks':'pq','Pushback lines':'push'}
START={'Case summary.':'summary','Must not miss.':'must',"On the patient's request.":'reqNote','Key actions scored:':'scored','Patient requests:':'req','Deadline:':'deadline'}
HDR={('Speaker','Line'),('Minute','Speaker','Interjection'),('Test','Result'),('Diagnosis','Likelihood','Basis'),('Test','Why'),('Test','When'),('Medicine or measure','Use','Note'),
 ('Panel','Simulated value'),('Doctor asks','Patient or attendant answers','Why it matters'),('Asked by','Question','Model doctor response'),('If the doctor','Speaker','Line')}
clean=lambda s:re.sub(r'\s+',' ',(s or '').replace('-\n','-')).strip()
def elements(pdf):
    for pg in pdf.pages:
        tabs=pg.find_tables(); box=[t.bbox for t in tabs]
        inside=lambda o:any(b[0]-1<=o['x0'] and o['x1']<=b[2]+1 and b[1]-1<=o['top'] and o['bottom']<=b[3]+1 for b in box)
        els=[(l['top'],'line',l['text'],l['bottom']) for l in pg.filter(lambda o:o['object_type']!='char' or not inside(o)).extract_text_lines()]
        els+=[(t.bbox[1],'table',t.extract(),t.bbox[3]) for t in tabs]
        prev=None
        for top,k,v,bot in sorted(els,key=lambda e:e[0]):
            if k=='line' and (v.startswith('Draft case set.') ): continue
            yield k,v,(top-prev>4 if prev is not None else False); prev=bot
        yield 'pagebreak',None,False
HDR_MAX=(1,2,3)
cases,cur,sec={},None,None
def new(L,t):
    return {'L':L,'title':t,'lines':{},'tables':{}}
for k,v,gap in elements(pdfplumber.open(sys.argv[1])):
    if k=='pagebreak': continue
    if k=='line':
        m=re.match(r'^Case ([A-H])\. (.+)$',v)
        if m: cur=cases.setdefault(m[1],new(m[1],m[2])); sec='head'; continue
        if not cur: continue
        if v.strip() in SEC: sec=SEC[v.strip()]; continue
        st=next((x for x in START if v.startswith(x)),None)
        if st: sec=START[st]; v=v[len(st):].strip() if st in('Patient requests:','Deadline:') else v
        cur['lines'].setdefault(sec,[]).append((v,gap))
    elif cur:
        rows=[[clean(c) for c in r if c is not None] for r in v]   # keep genuinely empty cells (e.g. blank Note)
        rows=[r for r in rows if any(r) and tuple(x for x in r if x) not in HDR]
        rows=[[x for x in r if x or len(r)<=len(HDR_MAX)] if len(r)>3 else r for r in rows]
        cur['tables'].setdefault('clock' if sec=='deadline' else sec,[]).extend(rows)
def para(ls):   # list of paragraphs
    out=[]
    for t,g in ls:
        if out and not g: out[-1]+=('' if out[-1].endswith('-') else ' ')+t
        else: out.append(t)
    return out
def bullets(ls):
    out=[]
    for t,g in ls:
        if t.startswith('•'): out.append(t.lstrip('• ').strip())
        elif out: out[-1]+=('' if out[-1].endswith('-') else ' ')+t
    return out
def lines(ls):   # one item per line, lowercase-leading lines continue the previous one
    out=[]
    for t,g in ls:
        if out and t[:1].islower(): out[-1]+=' '+t
        else: out.append(t)
    return out
def rows(c,s,keys): return [dict(zip(keys,r)) for r in c['tables'].get(s,[]) if len(r)==len(keys)]
res={}
for L,c in sorted(cases.items()):
    ln=c['lines'];J=lambda s:' '.join(para(ln.get(s,[])))
    head=' '.join(t for t,_ in ln.get('head',[]))
    f=dict(re.findall(r'(Cell|True condition \(hidden\)|Setting|Patient|With): (.*?)(?=(?: (?:Cell|True condition \(hidden\)|Setting|Patient|With): )|$)',head))
    cell=f.get('Cell','')
    res[L]={'L':L,'title':c['title'],'cell':cell,'hi':cell.startswith('High'),'clk':'no clock' not in cell,
     'mins':int((re.search(r'\((\d+) minutes\)',cell) or [0,0])[1]),
     'setting':f.get('Setting',''),'patient':f.get('Patient',''),'with':f.get('With',''),'hidden':f.get('True condition (hidden)',''),
     'story':para(ln.get('story',[])),'opening':rows(c,'opening',['s','l']),
     'deadline':J('deadline'),'clock':rows(c,'clock',['m','s','l']),'pressure':J('pressure'),
     'req':[x.strip() for x in J('req').split(';') if x.strip()],
     'vitals':lines(ln.get('vitals',[]))+[' '.join(r) for r in c['tables'].get('vitals',[])+c['tables'].get('vitals0',[])],
     'exam':bullets(ln.get('exam',[])),'results':rows(c,'results',['t','r']),
     'summary':J('summary'),'dx':rows(c,'dx',['n','lik','basis']),'must':J('must'),'sq':bullets(ln.get('sq',[])),
     'tests':rows(c,'tests',['t','why']),'related':rows(c,'related',['t','when']),'meds':rows(c,'meds',['n','use','note']),
     'cautions':bullets(ln.get('cautions',[])),'reqNote':J('reqNote'),'sim':rows(c,'sim',['p','v']),
     'ref':J('ref'),'scored':J('scored'),'dq':rows(c,'dq',['ask','ans','why']),'pq':rows(c,'pq',['by','q','a']),'push':rows(c,'push',['when','s','l'])}
json.dump(res,open('static/cases.json','w'),ensure_ascii=False,indent=0)
for L,r in res.items(): print(L,r['cell'],{k:len(v) for k,v in r.items() if isinstance(v,list)})
