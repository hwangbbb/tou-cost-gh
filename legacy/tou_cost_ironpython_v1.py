# TOU Energy Cost for Ladybug Tools / Grasshopper
# Version 1.0.0  (2026-08-31)  LEGACY, superseded by src/tou_cost.py v2
# Repo: see README.md for install, method, and rate references.
#
# Default rates are Con Edison Small Business Time-of-Use DELIVERY rates,
# retrieved 2026-08-31 from
#   https://www.coned.com/en/accounts-billing/your-bill/time-of-use
# They exclude supply, surcharges, and taxes. See rates/ for the record.
#
# Legacy GhPython component (IronPython 2). All inputs except the two data
# collections are optional; unconnected inputs fall back to the current
# rate sheet so the component runs with just _elec_data wired.
#
# INPUTS (right-click to rename, Access and hints per table)
#   _elec_data     Item, No Type Hint   hourly kWh collection, electricity
#   _gas_data      Item, No Type Hint   hourly kWh collection, gas, optional
#   peak_summer_   Item, No Type Hint   $/kWh, default 0.5443
#   peak_winter_   Item, No Type Hint   $/kWh, default 0.2680
#   offpeak_       Item, No Type Hint   $/kWh, default 0.0199
#   summer_mo_     List, No Type Hint   months on summer rate, default 6,7,8,9
#   peak_hrs_      List, No Type Hint   two ints, start and end hour,
#                                       default 8,22 (8am up to but not incl 10pm)
#   start_day_of_week_   Item, No Type Hint
#                  weekday of Jan 1 in the run period, matching the E+
#                  RunPeriod field "Day of Week for Start Day".
#                  Accepts a name ('Sunday') or an int 0=Mon..6=Sun.
#                  Default Sunday. Check it whenever the weather file or
#                  RunPeriod changes, a wrong value silently shifts the
#                  weekday peak buckets.
#   gas_rate_      Item, No Type Hint   $/kWh gas, default 0.0387
#
#   Large business / demand tariffs, leave unconnected for small service:
#   demand_rate_   Item, No Type Hint   $/kW on the monthly peak, default 0
#   monthly_charge_ Item, No Type Hint  fixed $ per month, default 0
#   demand_mult_   Item, No Type Hint   factor converting hourly-average peak
#                                       to billing-interval peak, default 1.0.
#                                       1.05-1.20 typical for 15-min metering,
#                                       closer to 1.0 for flat loads.
#
# OUTPUTS
#   report         text: annual totals, rates used, four TOU buckets
#   monthly_cost   Ladybug MonthlyCollection, USD per month, all fuels and
#                  charges. Wire to LB Monthly Chart for a bar chart, or to
#                  LB Deconstruct Data for the 12 numbers.
#   monthly_peak   Ladybug MonthlyCollection, kW. Highest hourly-average
#                  electric demand in each month. Same wiring options.
#   peak_times     12 strings, when each month's peak occurred,
#                  e.g. "Aug 02 13:00-14:00". Wire to a Panel.
#
# Peak period is weekdays only (Mon-Fri), which is fixed in the script since
# every TOU tariff seen so far uses it. Edit PEAK_DAYS below if one doesn't.

MD = (31,28,31,30,31,30,31,31,30,31,30,31)
MN = ('Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec')
PEAK_DAYS = (0,1,2,3,4)          # 0=Mon ... 6=Sun

from ladybug.datacollection import MonthlyCollection
from ladybug.header import Header
from ladybug.analysisperiod import AnalysisPeriod
from ladybug.datatype.generic import GenericType
from ladybug.datatype.power import Power


def unwrap(o):
    n = 0
    while o is not None and hasattr(o, 'Value') and n < 5:
        o = o.Value; n += 1
    return o


def vals(o):
    o = unwrap(o)
    return list(o.values) if o is not None and hasattr(o, 'values') else None


def num(v, fb):
    v = unwrap(v)
    if v is None:
        return fb
    try:
        return float(v)
    except (TypeError, ValueError):
        return fb


def ints(v, fb):
    if v is None:
        return list(fb)
    try:
        items = list(v)
    except TypeError:
        items = [v]
    out = []
    for i in items:
        try:
            out.append(int(float(unwrap(i))))
        except (TypeError, ValueError):
            pass
    return out if out else list(fb)


def weekday(v, fb):
    """'Sunday', 'sun', 6, or 6.0 all resolve. 0=Mon ... 6=Sun."""
    v = unwrap(v)
    if v is None:
        return fb
    names = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')
    try:
        return int(float(v)) % 7
    except (TypeError, ValueError):
        pass
    s = str(v).strip().lower()[:3]
    return names.index(s) if s in names else fb


ps  = num(peak_summer_, 0.5443)
pw  = num(peak_winter_, 0.2680)
op  = num(offpeak_,     0.0199)
sm  = set(ints(summer_mo_, (6,7,8,9)))
ph  = ints(peak_hrs_, (8,22))
h0, h1 = min(ph[0], ph[-1]), max(ph[0], ph[-1])
j1  = weekday(start_day_of_week_, 6)
gr  = num(gas_rate_, 0.0387)
dr  = num(demand_rate_, 0.0)
mch = num(monthly_charge_, 0.0)
dm  = num(demand_mult_, 1.0)

e = vals(_elec_data)
g = vals(_gas_data)
report = []
monthly_cost = None
monthly_peak = None
peak_times = []

if e is None:
    report = ['_elec_data is not an hourly data collection, check the wire']
else:
    # calendar stamp per hour: (month 0-11, hour 0-23, weekday 0=Mon)
    st = []
    doy = 0
    for m in range(12):
        for _ in range(MD[m]):
            wd = (j1 + doy) % 7
            for h in range(24):
                st.append((m, h, wd))
            doy += 1

    n = min(len(e), 8760)
    b = {'sp':[0.,0.], 'so':[0.,0.], 'wp':[0.,0.], 'wo':[0.,0.]}
    mc = [0.]*12
    mpk = [[0., None]]*0
    mpk = [[0.0, ''] for _ in range(12)]     # monthly elec peak kW, timestamp
    et = 0.
    doy = 0
    for i in range(n):
        m, h, wd = st[i]
        pk = (wd in PEAK_DAYS) and (h0 <= h < h1)
        s = (m + 1) in sm
        r = (ps if pk else op) if s else (pw if pk else op)
        k = ('s' if s else 'w') + ('p' if pk else 'o')
        c = e[i]*r
        b[k][0] += e[i]; b[k][1] += c
        mc[m] += c; et += c
        if e[i] > mpk[m][0]:
            day_in_m = (i // 24) + 1
            # day within month
            dcum = 0
            for mm in range(m):
                dcum += MD[mm]
            mpk[m] = [e[i], '%s %02d %02d:00-%02d:00'
                      % (MN[m], i//24 - dcum + 1, h, h+1)]

    gt = 0.; gk = 0.
    if g is not None:
        for i in range(min(len(g), 8760)):
            c = g[i]*gr
            mc[st[i][0]] += c; gt += c; gk += g[i]

    ek = sum(e[:n])
    dt_tot = 0.0
    if dr > 0 or mch > 0:
        dt_tot = sum(p[0] for p in mpk) * dm * dr + 12.0 * mch

    report.append('ELECTRICITY  $%.2f   %.1f kWh   $%.4f/kWh blended'
                  % (et, ek, et/ek if ek else 0))
    if dt_tot > 0:
        report.append('DEMAND+FIXED $%.2f   (%.2f kW-yr billed at $%.2f/kW'
                      ' x%.2f, $%.2f/mo fixed)'
                      % (dt_tot, sum(p[0] for p in mpk)*dm, dr, dm, mch))
    report.append('NATURAL GAS  $%.2f   %.1f kWh (%.1f therms)'
                  % (gt, gk, gk/29.3071))
    report.append('COMBINED     $%.2f' % (et+gt+dt_tot))
    report.append('')
    report.append('Rates: summer pk %.4f, winter pk %.4f, offpk %.4f, gas %.4f'
                  % (ps, pw, op, gr))
    dnames = ('Mon','Tue','Wed','Thu','Fri','Sat','Sun')
    report.append('Summer months %s, peak hours %d-%d, Jan 1 = %s'
                  % (sorted(sm), h0, h1, dnames[j1]))
    report.append('')
    lab = {'sp':'Summer peak','so':'Summer off','wp':'Winter peak','wo':'Winter off'}
    for k in ('sp','so','wp','wo'):
        report.append('%-12s %9.1f kWh   $%9.2f' % (lab[k], b[k][0], b[k][1]))
    report.append('')
    ap = AnalysisPeriod()
    mvals = [mc[m] + mpk[m][0]*dm*dr + mch for m in range(12)]
    monthly_cost = MonthlyCollection(
        Header(GenericType('Energy Cost', 'USD'), 'USD', ap),
        mvals, list(range(1, 13)))
    monthly_peak = MonthlyCollection(
        Header(Power(), 'kW', ap),
        [mpk[m][0] for m in range(12)], list(range(1, 13)))
    peak_times = [mpk[m][1] for m in range(12)]

    report.append('Annual peak %.2f kW (hourly average) in %s'
                  % (max(p[0] for p in mpk), peak_times[
                      [p[0] for p in mpk].index(max(p[0] for p in mpk))]))
    report.append('Monthly cost and peak kW are on the monthly_cost and')
    report.append('monthly_peak outputs; wire them to LB Monthly Chart.')

    for line in report:
        print(line)
