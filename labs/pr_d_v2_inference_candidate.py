"""Synthetic-only PR D v2 inference corrections; no production integration."""
from __future__ import annotations
import math
from typing import Any, Iterable
import numpy as np
import statsmodels.api as sm
from scipy.stats import norm

def _invalid_result(n_eff: int, reason: str) -> dict[str, Any]:
    return {"status":"INVALID","metrics":{"n_eff":n_eff,"effect_size":None,"se":None,
            "p_empirical":None,"ci_low":None,"ci_high":None,"invalid_reason":reason},
            "bh_input_p":1.0}

def _insufficient_result(n_eff: int, reason: str) -> dict[str, Any]:
    return {"status":"INSUFFICIENT_POWER","metrics":{"n_eff":n_eff,"effect_size":None,"se":None,
            "p_empirical":None,"ci_low":None,"ci_high":None,"non_estimability_reason":reason},
            "bh_input_p":1.0}

def fit_logistic_mle_v2(y: Iterable[float], design_matrix: Iterable[Iterable[float]], *,
                        coefficient_index: int, min_n_eff: int=30) -> dict[str, Any]:
    """Contract v2: insufficient eligible n is a state, not a structural exception.
    effect_size and ci_low/high are all on beta (log-odds) scale; OR is separate.
    """
    yy=np.asarray(list(y),dtype=np.float64); xx=np.asarray(list(design_matrix),dtype=np.float64)
    if yy.ndim!=1 or xx.ndim!=2 or xx.shape[0]!=yy.size or yy.size==0:
        raise ValueError("logistic_input_shape_invalid")
    if not np.isfinite(yy).all() or not np.isfinite(xx).all(): raise ValueError("logistic_input_nonfinite")
    if not np.isin(yy,[0.,1.]).all(): raise ValueError("logistic_outcome_not_binary")
    n=int(yy.size)
    if type(min_n_eff) is not int or min_n_eff<1: raise ValueError("min_n_eff_invalid")
    if n<min_n_eff: return _insufficient_result(n,"n_eff_below_minimum")
    if xx.shape[1]==0 or type(coefficient_index) is not int or not 0<=coefficient_index<xx.shape[1]:
        raise ValueError("coefficient_index_invalid")
    if np.linalg.matrix_rank(xx)<xx.shape[1] or np.unique(yy).size<2:
        return _insufficient_result(n,"model_not_estimable")
    try:
        fit=sm.Logit(yy,xx).fit(disp=False,maxiter=100)
        if not getattr(fit,"mle_retvals",{}).get("converged",True):
            return _insufficient_result(n,"model_non_convergence")
        beta=float(fit.params[coefficient_index]); se=float(fit.bse[coefficient_index])
        p=float(fit.pvalues[coefficient_index])
        z=float(norm.ppf(.975)); lo=beta-z*se; hi=beta+z*se
        odds=math.exp(beta); orlo=math.exp(lo); orhi=math.exp(hi)
    except (np.linalg.LinAlgError, ValueError, OverflowError):
        return _insufficient_result(n,"model_not_estimable")
    vals=(beta,se,p,lo,hi,odds,orlo,orhi)
    if not all(math.isfinite(v) for v in vals) or se<=0 or not 0<=p<=1:
        return _insufficient_result(n,"model_not_estimable")
    return {"status":"ESTIMABLE","metrics":{"n_eff":n,"effect_size":beta,"se":se,
        "p_empirical":p,"ci_low":lo,"ci_high":hi,"odds_ratio":odds,
        "odds_ratio_ci_low":orlo,"odds_ratio_ci_high":orhi,
        "effect_scale":"log_odds","ci_scale":"log_odds","non_estimability_reason":None},
        "bh_input_p":p}

def fit_ols_log_positive_hc3_v2(outcomes: Iterable[float], design_matrix: Iterable[Iterable[float]], *,
                                coefficient_index: int, min_n_eff: int=30) -> dict[str, Any]:
    """Family II: n_eff counts all eligible rows; n_events counts eligible Y>0.
    Estimation uses positive rows only, but the contractual eligible-n gate is separate.
    """
    yy=np.asarray(list(outcomes),dtype=np.float64); xx=np.asarray(list(design_matrix),dtype=np.float64)
    if yy.ndim!=1 or xx.ndim!=2 or xx.shape[0]!=yy.size or yy.size==0:
        raise ValueError("ols_input_shape_invalid")
    if not np.isfinite(yy).all() or not np.isfinite(xx).all(): raise ValueError("ols_input_nonfinite")
    if np.any(yy<0): raise ValueError("ols_outcome_negative")
    if type(min_n_eff) is not int or min_n_eff<1: raise ValueError("min_n_eff_invalid")
    if type(coefficient_index) is not int or not 0<=coefficient_index<xx.shape[1]:
        raise ValueError("coefficient_index_invalid")
    n_eff=int(yy.size); positive=yy>0; n_events=int(positive.sum())
    base={"n_eff":n_eff,"n_events":n_events,
          "method_fingerprint":"ols-ln-positive-y-hc3-t-two-sided-v2"}
    if n_eff<min_n_eff: return {**_insufficient_result(n_eff,"n_eff_below_minimum"),"metrics":{
        **base,"effect_size":None,"se":None,"p_empirical":None,"ci_low":None,"ci_high":None,
        "non_estimability_reason":"n_eff_below_minimum"}}
    design=xx[positive]; y_positive=yy[positive]
    if n_events<=design.shape[1] or np.linalg.matrix_rank(design)<design.shape[1]:
        return {"status":"INSUFFICIENT_POWER","metrics":{**base,"effect_size":None,"se":None,
            "p_empirical":None,"ci_low":None,"ci_high":None,"non_estimability_reason":"model_not_estimable"},
            "bh_input_p":1.0}
    try:
        fit=sm.OLS(np.log(y_positive),design).fit(cov_type="HC3",use_t=True)
        beta=float(fit.params[coefficient_index]); se=float(fit.bse[coefficient_index])
        p=float(fit.pvalues[coefficient_index]); lo,hi=map(float,fit.conf_int(alpha=.05)[coefficient_index])
    except (np.linalg.LinAlgError,ValueError,FloatingPointError):
        return {"status":"INSUFFICIENT_POWER","metrics":{**base,"effect_size":None,"se":None,
            "p_empirical":None,"ci_low":None,"ci_high":None,"non_estimability_reason":"model_not_estimable"},
            "bh_input_p":1.0}
    if not all(math.isfinite(v) for v in (beta,se,p,lo,hi)) or se<=0 or not 0<=p<=1 or not lo<=beta<=hi:
        return {"status":"INSUFFICIENT_POWER","metrics":{**base,"effect_size":None,"se":None,
            "p_empirical":None,"ci_low":None,"ci_high":None,"non_estimability_reason":"model_not_estimable"},
            "bh_input_p":1.0}
    return {"status":"ESTIMABLE","metrics":{**base,"effect_size":beta,"se":se,"p_empirical":p,
        "ci_low":lo,"ci_high":hi,"non_estimability_reason":None,"covariance_type":"HC3",
        "contrast":"two_sided_t","effect_scale":"log_outcome","ci_scale":"log_outcome"},"bh_input_p":p}

def adjust_bh_frozen_family(rows: Iterable[dict[str,Any]], *, frozen_hypothesis_ids: Iterable[str]) -> list[dict[str,Any]]:
    """BH over the exact preregistered family; INVALID and non-estimable rows get adjustment p=1."""
    family=[dict(r) for r in rows]; expected=list(frozen_hypothesis_ids)
    if not expected or any(not isinstance(x,str) or not x for x in expected) or len(expected)!=len(set(expected)):
        raise ValueError("frozen_family_ids_invalid")
    ids=[r.get("hypothesis_id") for r in family]
    if len(ids)!=len(expected) or set(ids)!=set(expected) or len(ids)!=len(set(ids)):
        raise ValueError("fdr_family_membership_mismatch")
    ps=[]
    for row in family:
        metrics=row.get("metrics") if isinstance(row.get("metrics"),dict) else row
        status=row.get("status")
        if status=="ESTIMABLE":
            p=metrics.get("p_empirical")
            if isinstance(p,bool) or not isinstance(p,(int,float)) or not math.isfinite(float(p)) or not 0<=p<=1:
                raise ValueError("empirical_p_invalid")
            ps.append(float(p))
        elif status=="INVALID":
            if metrics.get("p_empirical") is not None: raise ValueError("invalid_empirical_p_must_be_null")
            ps.append(1.0)
        elif status=="INSUFFICIENT_POWER":
            if metrics.get("p_empirical") is not None: raise ValueError("nonestimable_empirical_p_must_be_null")
            ps.append(1.0)
        else: raise ValueError("fdr_member_status_unsupported")
    m=len(family); order=sorted(range(m),key=lambda i:(ps[i],i)); qs=[1.0]*m; running=1.0
    for rev in range(m-1,-1,-1):
        idx=order[rev]; running=min(running,ps[idx]*m/(rev+1)); qs[idx]=min(1.0,running)
    for i,row in enumerate(family):
        metrics=row.get("metrics") if isinstance(row.get("metrics"),dict) else row
        row["bh_input_p"]=ps[i]; row["fdr_q"]=qs[i]; row["family_m"]=m
        metrics["bh_input_p"]=ps[i]; metrics["fdr_q"]=qs[i]; metrics["family_m"]=m
    return family
