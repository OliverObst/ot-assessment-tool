#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Jul  8 08:46:21 2025

@author: Oliver Obst
"""
"""
Optimal‑transport inspired assessment analyser
• Multi‑mark items.  
• Default target: truncated normal (bounded 0–max, 80 % pass). Optionally `TARGET_DIST="beta"`.  
• Shows current vs **OT‑mapped** histogram (outline), band report, bimodality flag, and item advice.

Change: the preview histogram now uses each student’s exact OT‑mapped mark rather than a band‑average shift, eliminating the artificial pile‑up at the top end.
Run: `python ot_assessment_tool.py [marks.csv]`
"""

import sys, numpy as np, pandas as pd, matplotlib.pyplot as plt
from scipy.stats import truncnorm, beta
from scipy.optimize import brentq
from typing import Dict

# ---------------- tuning knobs -----------------------------
PASS_RATE_TARGET = 0.80      # mass ≥ pass mark
FACILITY_EASY   = 0.85
FACILITY_HARD   = 0.35
DISCRIM_POOR    = 0.15
MID_BAND_WIDTH  = 0.30
BAND_COUNT      = 5
TARGET_DIST     = "truncnorm"    # or "beta"
MAX_POINTS: Dict[str, float] = {}
# -----------------------------------------------------------

def load(path: str):
    df = pd.read_csv(path)
    if df.iloc[0,0] == "max":
        max_row, df = df.iloc[0], df.drop(0).reset_index(drop=True)
        max_dict = {c: float(max_row[c]) for c in df.columns if c.startswith("q")}
    else:
        max_dict = MAX_POINTS.copy()
    items = [c for c in df.columns if c.startswith("q")]
    df[items] = df[items].apply(pd.to_numeric, errors="coerce").fillna(0)
    for q in items:
        max_dict.setdefault(q, max(df[q].max(),1))
    df["total"] = df[items].sum(axis=1)
    return df, items, max_dict

# ---------- target distributions ---------------------------

def build_trunc(total_max):
    pass_mark, sigma = 0.5*total_max, total_max/6
    f = lambda mu: 1-truncnorm(((0-mu)/sigma),((total_max-mu)/sigma),loc=mu,scale=sigma).cdf(pass_mark)-PASS_RATE_TARGET
    mu = brentq(f, pass_mark*0.5, pass_mark*1.5)
    return truncnorm(((0-mu)/sigma), ((total_max-mu)/sigma), loc=mu, scale=sigma)

def build_beta_ppf(total_max):
    x_p = 0.5
    f = lambda a: 1-beta.cdf(x_p,a,a)-PASS_RATE_TARGET
    a= brentq(f,0.5,10)
    return lambda p: beta.ppf(p,a,a)*total_max, a

# ---------- plotting ---------------------------------------

def plot_hists(orig, mapped, pdf):
    plt.figure()
    bins = np.arange(np.floor(orig.min())-0.5, np.ceil(max(orig.max(),mapped.max()))+1.5,1)
    plt.hist(orig, bins=bins, alpha=0.5, density=True, label="current")
    plt.hist(mapped, bins=bins, histtype='step', density=True, linewidth=1.6, label="after OT mapping")
    x = np.linspace(0, bins[-1], 400)
    plt.plot(x, pdf(x), label=f"target {TARGET_DIST}")
    plt.xlabel("total marks"); plt.ylabel("density"); plt.legend(); plt.tight_layout(); plt.show()

# ---------- analytics --------------------------------------

def ot_band_report(sorted_scores, g_inv):
    n=len(sorted_scores)
    bands = pd.qcut(pd.Series(sorted_scores), BAND_COUNT, labels=False)
    shifts = g_inv((np.arange(n)+0.5)/n)-sorted_scores
    return shifts, bands

def item_stats(df, items, max_dict):
    corr = df[items+["total"]].corr()
    return pd.DataFrame([(q, df[q].mean()/max_dict[q], corr.loc[q,"total"]) for q in items], columns=["item","facility","discrimination"])

def detect_bimodal(scores,total_max):
    pass_mark, top = 0.5*total_max, 0.5*total_max+MID_BAND_WIDTH*total_max
    fails, mids, highs = (scores<pass_mark).mean(), ((scores>=pass_mark)&(scores<top)).mean(), (scores>=top).mean()
    return (mids<0.25 and fails>0.1 and highs>0.1), fails, mids, highs

def diagnose(df_items,bimodal):
    recs=[]
    if bimodal:
        recs.append("Distribution strongly bimodal – add medium‑difficulty items or partial credit to build the middle band.")
    for _,r in df_items.iterrows():
        if r.facility>FACILITY_EASY and r.discrimination<DISCRIM_POOR:
            recs.append(f"{r['item']} too easy, poor discrimination – rewrite or down‑weight.")
        elif r.facility<FACILITY_HARD:
            recs.append(f"{r['item']} too hard – split or add partial credit.")
    return recs

# ---------- main -------------------------------------------

def main():
    if len(sys.argv)>2:
        print("Usage: python ot_assessment_tool.py [marks.csv]"); sys.exit(1)
    filename = sys.argv[1] if len(sys.argv)==2 else "marks.csv"

    df, items, max_dict = load(filename)
    scores, total_max = df["total"].values, sum(max_dict.values())

    if TARGET_DIST=="beta":
        g_inv, alpha = build_beta_ppf(total_max)
        pdf = lambda x: beta.pdf(x/total_max,alpha,alpha)/total_max
    else:
        tn = build_trunc(total_max)
        g_inv, pdf = tn.ppf, tn.pdf

    # OT mapping per student (sorted ranks) to avoid pile‑ups
    order = np.argsort(scores)
    mapped = np.empty_like(scores,dtype=float)
    mapped[order] = g_inv((np.arange(len(scores))+0.5)/len(scores))
    mapped = np.clip(mapped,0,total_max)

    # band summary for diagnostics
    shifts, bands = ot_band_report(np.sort(scores), g_inv)
    print(f"average shift to target {TARGET_DIST}: {shifts.mean():+.2f}\n")
    for i,s in pd.Series(shifts).groupby(bands).mean().items():
        print(f"  band {i+1}/{BAND_COUNT}: {s:+.2f} marks")

    plot_hists(scores, mapped, pdf)

    stats=item_stats(df,items,max_dict)
    bimodal,pf,pm,ph=detect_bimodal(scores,total_max)
    if bimodal:
        print(f"\nbimodality – fail {pf:.0%}, mid {pm:.0%}, high {ph:.0%}")

    print("\nitem summary (facility=mean/max)\n--------------------------------")
    print(stats.to_string(index=False, float_format="{:.2f}".format))

    recs=diagnose(stats,bimodal)
    print("\nrecommendations\n---------------")
    print("none" if not recs else "\n • ".join([""]+recs))

if __name__=="__main__":
    main()

