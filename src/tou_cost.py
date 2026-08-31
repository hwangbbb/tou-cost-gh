# TOU Energy Cost for Ladybug Tools / Grasshopper
# Version 2.0.0  (2026-08-31)
#
# ENGINE-AGNOSTIC BUILD. Runs in the Rhino 8 Python 3 component, the
# IronPython 2 component, or legacy GhPython. It never touches a Ladybug
# object directly. Numbers come in, numbers and a JSON file go out, and
# LB Load Data rebuilds proper collections inside the Ladybug engine.
#
# Default rates are Con Edison Small Business Time-of-Use DELIVERY rates,
# retrieved 2026-08-31 from
#   https://www.coned.com/en/accounts-billing/your-bill/time-of-use
# They exclude supply, surcharges, and taxes. See rates/ for the record.
#
# UPSTREAM WIRING
#   HB Read Custom Result  ->  LB Deconstruct Data  ->  values  ->  _elec_kwh
#   same for gas, if any                                       ->  _gas_kwh
#
# INPUTS  (Access as listed, Type hint: float for the two kWh lists,
#          No Type Hint for the rest)
#   _elec_kwh        List   8760 hourly kWh values, electricity
#   _gas_kwh         List   8760 hourly kWh values, gas, optional
#   peak_summer_     Item   $/kWh, default 0.5443
#   peak_winter_     Item   $/kWh, default 0.2680
#   offpeak_         Item   $/kWh, default 0.0199
#   summer_mo_       List   months on summer rate, default 6,7,8,9
#   peak_hrs_        List   start, end hour; end exclusive; default 8,22
#   start_day_of_week_  Item  weekday of Jan 1, name or 0=Mon..6=Sun,
#                             default Sunday. Matches the E+ RunPeriod
#                             field "Day of Week for Start Day".
#   gas_rate_        Item   $/kWh gas, default 0.0387
#   demand_rate_     Item   $/kW on monthly peak, default 0
#   monthly_charge_  Item   fixed $/month, default 0
#   demand_mult_     Item   hourly-to-interval peak factor, default 1.0
#   folder_          Item   where to write JSON files, default system temp
#
# OUTPUTS
#   report           text summary, wire to a Panel (Multiline Data on)
#   hourly_cost      8760 floats, $ per hour, all fuels (numbers only)
#   hourly_file      path to JSON. Wire to LB Load Data. Gives an hourly
#                    collection in USD. Feed it to LB Hourly Plot, or to
#                    LB Monthly Chart which sums it to monthly bars.
#   monthly_file     path to JSON. Wire to a second LB Load Data. Gives
#                    two monthly collections: cost in USD, peak in kW.
#   peak_times       12 strings, when each month's peak occurred
#
# WHY FILES: Grasshopper runs several Python engines side by side. Objects
# built in one are opaque to the others, which is what produced errors like
# "must contain data collections, got MonthlyCollection". Floats, strings,
# and files cross every engine boundary. LB Load Data does the rebuild.

import os
import json
import tempfile

MD = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
MN = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
      'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')
DN = ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')
PEAK_DAYS = (0, 1, 2, 3, 4)


def unwrap(o):
    n = 0
    while o is not None and hasattr(o, 'Value') and n < 5:
        o = o.Value
        n += 1
    return o


def num(v, fb):
    v = unwrap(v)
    if v is None:
        return fb
    try:
        return float(v)
    except (TypeError, ValueError):
        return fb


def nums(v):
    """List input of numbers -> python list of floats, or None."""
    if v is None:
        return None
    try:
        items = list(v)
    except TypeError:
        items = [v]
    out = []
    for i in items:
        try:
            out.append(float(unwrap(i)))
        except (TypeError, ValueError):
            return None
    return out if out else None


def ints(v, fb):
    got = nums(v)
    return [int(x) for x in got] if got else list(fb)


def weekday(v, fb):
    v = unwrap(v)
    if v is None:
        return fb
    try:
        return int(float(v)) % 7
    except (TypeError, ValueError):
        pass
    s = str(v).strip().lower()[:3]
    names = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')
    return names.index(s) if s in names else fb


AP = {"st_month": 1, "st_day": 1, "st_hour": 0, "end_month": 12,
      "end_day": 31, "end_hour": 23, "timestep": 1,
      "is_leap_year": False, "type": "AnalysisPeriod"}


def hourly_dict(name, unit, values, meta):
    return {"type": "HourlyContinuous",
            "header": {"type": "Header",
                       "data_type": {"type": "GenericDataType",
                                     "data_type": "GenericType",
                                     "name": name, "base_unit": unit},
                       "unit": unit, "analysis_period": AP,
                       "metadata": meta},
            "values": values}


def monthly_dict(dtype, unit, values, meta, generic_name=None):
    if generic_name:
        dt = {"type": "GenericDataType", "data_type": "GenericType",
              "name": generic_name, "base_unit": unit}
    else:
        dt = {"type": "DataType", "data_type": dtype, "name": dtype}
    return {"type": "Monthly",
            "header": {"type": "Header", "data_type": dt, "unit": unit,
                       "analysis_period": AP, "metadata": meta},
            "values": values, "datetimes": list(range(1, 13))}


ps = num(peak_summer_, 0.5443)
pw = num(peak_winter_, 0.2680)
op = num(offpeak_, 0.0199)
sm = set(ints(summer_mo_, (6, 7, 8, 9)))
ph = ints(peak_hrs_, (8, 22))
h0, h1 = min(ph[0], ph[-1]), max(ph[0], ph[-1])
j1 = weekday(start_day_of_week_, 6)
gr = num(gas_rate_, 0.0387)
dr = num(demand_rate_, 0.0)
mch = num(monthly_charge_, 0.0)
dm = num(demand_mult_, 1.0)
fold = unwrap(folder_)
fold = str(fold) if fold else os.path.join(tempfile.gettempdir(), 'tou_cost')

e = nums(_elec_kwh)
g = nums(_gas_kwh)

report = []
hourly_cost = []
hourly_file = None
monthly_file = None
peak_times = []

if e is None or len(e) < 8760:
    got = unwrap(_elec_kwh)
    report = ['_elec_kwh needs 8760 numbers.',
              'Received: %s with %s items'
              % (type(got).__name__,
                 len(got) if hasattr(got, '__len__') else 'n/a'),
              'Wire: HB Read Custom Result -> LB Deconstruct Data -> values',
              'Set _elec_kwh to List Access, type hint float.']
else:
    e = e[:8760]
    if g is not None and len(g) >= 8760:
        g = g[:8760]
    else:
        g = None

    # calendar stamps
    st = []
    doy = 0
    for m in range(12):
        for d in range(MD[m]):
            wd = (j1 + doy) % 7
            for h in range(24):
                st.append((m, d + 1, h, wd))
            doy += 1

    b = {'sp': [0., 0.], 'so': [0., 0.], 'wp': [0., 0.], 'wo': [0., 0.]}
    mc = [0.] * 12
    mpk = [[0.0, ''] for _ in range(12)]
    rate_h = [0.] * 8760
    et = 0.
    for i in range(8760):
        m, d, h, wd = st[i]
        pk = (wd in PEAK_DAYS) and (h0 <= h < h1)
        s = (m + 1) in sm
        r = (ps if pk else op) if s else (pw if pk else op)
        k = ('s' if s else 'w') + ('p' if pk else 'o')
        c = e[i] * r
        rate_h[i] = r
        hourly_cost.append(c)
        b[k][0] += e[i]
        b[k][1] += c
        mc[m] += c
        et += c
        if e[i] > mpk[m][0]:
            mpk[m] = [e[i], '%s %02d %02d:00-%02d:00' % (MN[m], d, h, h + 1)]

    gt = 0.
    gk = 0.
    if g is not None:
        for i in range(8760):
            c = g[i] * gr
            hourly_cost[i] += c
            mc[st[i][0]] += c
            gt += c
            gk += g[i]

    ek = sum(e)
    peaks = [p[0] for p in mpk]
    dt_tot = sum(peaks) * dm * dr + 12.0 * mch if (dr > 0 or mch > 0) else 0.
    # spread demand and fixed charges evenly across each month's hours
    if dt_tot > 0:
        hcount = [MD[m] * 24 for m in range(12)]
        for i in range(8760):
            m = st[i][0]
            hourly_cost[i] += (peaks[m] * dm * dr + mch) / hcount[m]

    mvals = [mc[m] + peaks[m] * dm * dr + mch for m in range(12)]
    peak_times = [p[1] for p in mpk]

    # ---- files for LB Load Data ----
    meta = {"source": "tou_cost 2.0.0",
            "rates": "sp %.4f wp %.4f op %.4f gas %.4f" % (ps, pw, op, gr)}
    try:
        if not os.path.isdir(fold):
            os.makedirs(fold)
        hourly_file = os.path.join(fold, 'tou_hourly_cost.json')
        with open(hourly_file, 'w') as f:
            json.dump([hourly_dict('Energy Cost', 'USD', hourly_cost, meta),
                       hourly_dict('Energy Rate', 'USD/kWh', rate_h, meta)], f)
        monthly_file = os.path.join(fold, 'tou_monthly.json')
        with open(monthly_file, 'w') as f:
            json.dump([monthly_dict(None, 'USD', mvals, meta,
                                    generic_name='Energy Cost'),
                       monthly_dict('Power', 'kW', peaks, meta)], f)
    except Exception as ex:
        hourly_file = monthly_file = None
        report.append('Could not write JSON files: %s' % ex)

    # ---- report ----
    report.append('ELECTRICITY  $%.2f   %.1f kWh   $%.4f/kWh blended'
                  % (et, ek, et / ek if ek else 0))
    if dt_tot > 0:
        report.append('DEMAND+FIXED $%.2f   (%.2f kW-yr at $%.2f/kW x%.2f,'
                      ' $%.2f/mo)' % (dt_tot, sum(peaks) * dm, dr, dm, mch))
    report.append('NATURAL GAS  $%.2f   %.1f kWh (%.1f therms)'
                  % (gt, gk, gk / 29.3071))
    report.append('COMBINED     $%.2f' % (et + gt + dt_tot))
    report.append('')
    report.append('Rates: summer pk %.4f, winter pk %.4f, offpk %.4f, gas %.4f'
                  % (ps, pw, op, gr))
    report.append('Summer months %s, peak hours %d-%d, Jan 1 = %s'
                  % (sorted(sm), h0, h1, DN[j1]))
    report.append('')
    lab = {'sp': 'Summer peak', 'so': 'Summer off',
           'wp': 'Winter peak', 'wo': 'Winter off'}
    for k in ('sp', 'so', 'wp', 'wo'):
        report.append('%-12s %9.1f kWh   $%9.2f' % (lab[k], b[k][0], b[k][1]))
    report.append('')
    imax = peaks.index(max(peaks))
    report.append('Annual peak %.2f kW (hourly average) in %s'
                  % (peaks[imax], peak_times[imax]))
    report.append('')
    report.append('hourly_file  -> LB Load Data -> [0] cost USD, [1] rate USD/kWh')
    report.append('monthly_file -> LB Load Data -> [0] cost USD, [1] peak kW')

for line in report:
    print(line)
