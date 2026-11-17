"""
nlp/crisis_classifier.py
========================
Rule-based crisis-event classifier for news headlines.

The report lists "crisis-event classifier" as missing (Section VII-B) and
recommends one (Section IX-3). This is a transparent keyword classifier:
each headline gets at most one category, checked in priority order, so the
dashboard can show *what kind* of issue drives a company's risk rather than
only how negative the coverage is.

It is deliberately simple and explainable (every match can be traced to a
keyword). It is not a trained model and has not been validated on labelled
data; use the Validation tab to label headlines and measure it.
"""

import re
from typing import Dict, List, Optional

# (category, pattern). Order matters: the first match wins.
_CATEGORY_RULES = [
    ("Fraud & Governance", r"\bfraud\w*|\bscam\w*|money[- ]laundering|\bpmla\b|\bed raids?\b|\braids?\b|\bcbi\b|"
                           r"\barrest\w*|embezzl\w*|misconduct|whistle-?blower|governance (lapse|issue|concern)|"
                           r"short[- ]seller|hindenburg|viceroy|manipulat\w*|insider trading|brib\w*|indict\w*|"
                           r"forensic audit|siphon\w*|accounting (lapse|irregular\w*)|irregularit\w*"),
    ("Regulatory Action",  r"\brbi\b|\bsebi\b|us ?fda|\bfda\b|\bcci\b|\birdai\b|\btrai\b|\bdgca\b|\bnhai\b|"
                           r"\bcdsco\b|\bfssai\b|\bnpci\b|\bmca\b|regulator\w*|\bbann?(ed|s)?\b|\bbarred\b|\bbars\b|"
                           r"restrict\w*|penalt\w*|\bfined?\b|show[- ]cause|warning letter|import alert|"
                           r"form 483|\d+ observations|observations? (from|by) (the )?us ?fda|non-?complian\w*|licen[cs]e (cancel\w*|suspend\w*|revok\w*)|"
                           r"crack(s|ed)? down|curbs?\b|directive|adjudicat\w*"),
    ("Tax Dispute",        r"\bgst\b|tax (demand|notice|evasion|dispute|raid)|income[- ]tax|\bdggi\b|"
                           r"customs duty|tax authorities"),
    ("Legal & Litigation", r"\bcourt\b|lawsuit|\bsued?\b|\bsues\b|\bnclt\b|\bnclat\b|tribunal|arbitration|"
                           r"verdict|litigation|\bplea\b|\bpil\b|\bfir\b|legal (battle|action|notice|tangle)|"
                           r"class action|contempt|summon\w*"),
    ("Data & Cyber",       r"data (breach|leak)|\bleak(ed|s)?\b|\bhack\w*|cyber[- ]?attack|cyber\w*|ransomware|"
                           r"phishing|privacy"),
    ("Safety & Product",   r"\brecall\w*|defect\w*|\bfire\b|explosion|blast|accident|safety|contaminat\w*|"
                           r"injur\w*|\bdeaths?\b|\bdied\b|\bcrash(es|ed)?\b(?! in share)|faulty|"
                           r"quality (issue|concern|lapse)|adulterat\w*|food poisoning|spurious"),
    ("Service Outage",     r"outage|disruption|\bglitch\w*|downtime|services? (down|hit|disrupted)|"
                           r"network (issue|failure)|flight (delay|cancell?ation)s?|cancels? flights"),
    ("Labour & Protest",   r"\bstrikes?\b|protest\w*|layoffs?|lay off|job cuts?|retrench\w*|\bunions?\b|"
                           r"workers|\bwages?\b|boycott\w*|backlash|outrage|trolled|uproar|agitation"),
    ("Leadership Change",  r"\b(ceo|cfo|coo|md|chairman|chairperson|director|founder|president|head)\b[^.]{0,40}?"
                           r"\b(quits?|exits?|ousted|sacked)\b|resign\w*|steps? down|stepping down|ousted|"
                           r"succession|leadership (change|crisis|exit)|management (exit|churn)"),
    ("Financial Distress", r"\bdefault\w*|\bdebt\b|downgrade\w*|insolvency|bankrupt\w*|liquidity|\bnpas?\b|"
                           r"bad loans|write-?off|impairment|rating cut|cash crunch|salary delay|"
                           r"unpaid (dues|salaries)|going concern|loss(es)? widen|net loss|in the red"),
    ("ESG & Environment",  r"emission\w*|pollut\w*|environment\w*|clearance|\besg\b|climate|greenwash\w*|"
                           r"deforest\w*|carbon|toxic|effluent|oil spill"),
    ("Market & Earnings",  r"shares? (fall|falls|fell|slump\w*|plunge\w*|tumble\w*|drop\w*|crash\w*|sink\w*|"
                           r"slide\w*|decline\w*|tank\w*|dip\w*)|stock (falls|plunges|tanks|slumps|drops)|"
                           r"profit (falls|fell|drops|declines|slumps|plunges)|miss(es)? estimates|"
                           r"margin pressure|target cut|cuts? target|\bsell\b rating|downgrades?|underperform\w*|"
                           r"52-week low|weak (q[1-4]|quarter|guidance|demand)|guidance cut|top losers?|"
                           r"m-?cap (erosion|wiped)|wipes? out|"
                           r"\b(fell|dropped|plunged|tumbled|slumped|crashed|declined|tanked|sank|slid|falls?|drops?|"
                           r"plunges?|tumbles?|slumps?|crash(es)?|declines?|tanks?|sinks?|slides?)\b[^.%]{0,25}?\d+(\.\d+)?\s?%"),
]

_COMPILED = [(cat, re.compile(pat, re.I)) for cat, pat in _CATEGORY_RULES]

GENERAL = "General Coverage"
CATEGORIES = [c for c, _ in _CATEGORY_RULES] + [GENERAL]

# Regulators / enforcement bodies whose involvement raises stakeholder criticality
_REGULATORS = re.compile(
    r"\b(RBI|SEBI|US ?FDA|USFDA|FDA|CCI|IRDAI|TRAI|DGCA|CDSCO|FSSAI|NPCI|MCA|ED|CBI|SFIO|NCLT|"
    r"Supreme Court|High Court|DGGI|Income[- ]Tax|income[- ]tax|CCPA)\b")


def classify(text: str) -> Dict[str, Optional[str]]:
    """Return {'category': ..., 'keyword': matched text or None}."""
    t = text or ""
    for cat, rx in _COMPILED:
        m = rx.search(t)
        if m:
            return {"category": cat, "keyword": m.group(0)}
    return {"category": GENERAL, "keyword": None}


def regulators_mentioned(text: str) -> List[str]:
    found = {m.group(0).upper().replace(" ", "") for m in _REGULATORS.finditer(text or "")}
    return sorted(found)


def tag_articles(articles: List[dict]) -> None:
    """Add 'category', 'category_keyword' and 'regulators' to each article in place."""
    for a in articles:
        text = a.get("title", "")
        c = classify(text)
        a["category"] = c["category"]
        a["category_keyword"] = c["keyword"]
        a["regulators"] = regulators_mentioned(text)
