# TOU Energy Cost for Ladybug Tools / Grasshopper
# Version 3.1.1  (2026-08-31)
#
# DIRECT BUILD. Takes Ladybug hourly collections straight from HB Read
# Custom Result and returns Ladybug collections that LB Hourly Plot and
# LB Monthly Chart accept. No LB Deconstruct Data, no LB Load Data.
#
# Works in the legacy GhPython Script component AND in the Rhino 8 Script
# component in IronPython 2 mode. Does NOT work in Python 3 mode; CPython
# cannot see IronPython objects. For Python 3 use v2 (JSON bridge).
#
# HOW IT AVOIDS THE ENGINE PROBLEM
#   This script never imports ladybug. Importing it from a second engine
#   loads a second copy of the module, and objects built from that copy
#   fail LB components' isinstance checks. Instead every output is built
#   with type(_elec_data).from_dict(...), i.e. with the class the incoming
#   object already carries, which is the class LBT itself uses.
#
# WHAT 3.1 HANDLES THAT 3.0 DID NOT
#   - a list of collections on either data input is summed (e.g. several
#     electric end uses, or PV plus grid)
#   - units other than kWh are converted (J, GJ, Wh, kBtu, therm ...)
#   - power collections (kW) are converted to kWh per interval
#   - sub-hourly timesteps are summed to hourly
#   - leap-year runs (8784 hours) are handled
#   - partial run periods, wrong lengths, mismatched gas are refused with
#     a message instead of silently truncated
#   - every conversion and assumption is listed under Notes in the report
#
# Default rates are Con Edison Small Business Time-of-Use DELIVERY rates,
# retrieved 2026-08-31 from
#   https://www.coned.com/en/accounts-billing/your-bill/time-of-use
# They exclude supply, surcharges, and taxes. See rates/ for the record.
#
# INPUTS  (Item Access, No Type Hint, except the two lists)
#   _elec_data       Item   hourly collection(s) in kWh, electricity
#   _gas_data        Item   hourly collection(s) in kWh, gas, optional
#   peak_summer_     Item   $/kWh, default 0.5443
#   peak_winter_     Item   $/kWh, default 0.2680
#   offpeak_         Item   $/kWh, default 0.0199
#   summer_mo_       List   months on summer rate, default 6,7,8,9
#   peak_hrs_        List   start, end hour; end exclusive; default 8,22
#   start_day_of_week_  Item  weekday of Jan 1, name or 0=Mon..6=Sun,
#                             default Sunday (E+ RunPeriod "Day of Week
#                             for Start Day")
#   gas_rate_        Item   $/kWh gas, default 0.0387
#   demand_rate_     Item   $/kW on monthly peak, default 0
#   monthly_charge_  Item   fixed $/month, default 0
#   demand_mult_     Item   hourly-to-interval peak factor, default 1.0
#
# OUTPUTS
#   report        text summary, Panel with Multiline Data
#   hourly_cost   Hourly collection, USD, all fuels and charges
#                 -> LB Hourly Plot, or LB Monthly Chart (sums to months)
#   hourly_rate   Hourly collection, USD per kWh, the electric rate in
#                 effect each hour -> LB Hourly Plot to picture the tariff
#   monthly_cost  Monthly collection, USD -> LB Monthly Chart
#   monthly_peak  Monthly collection, kW -> LB Monthly Chart
#   peak_times    12 strings, when each month's peak occurred

MD = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
MN = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
      'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')
DN = ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')
PEAK_DAYS = (0, 1, 2, 3, 4)
TO_KWH = {'kwh': 1.0, 'wh': 1e-3, 'mwh': 1e3, 'j': 1.0 / 3.6e6,
          'kj': 1.0 / 3600.0, 'mj': 1.0 / 3.6, 'gj': 1000.0 / 3.6,
          'kbtu': 1.0 / 3.41214, 'btu': 1.0 / 3412.14,
          'mmbtu': 1000.0 / 3.41214, 'therm': 29.3071}
NOTES = []
BUILD_LOG = []


# ------------------------------------------------------------- inputs
def unwrap(o):
    n = 0
    while o is not None and hasattr(o, 'Value') and n < 5:
        o = o.Value
        n += 1
    return o


def num(v, fb):
    v = unwrap(v)
    if isinstance(v, (list, tuple)):
        v = unwrap(v[0]) if len(v) else None
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


def collections(obj):
    """Return a list of Ladybug collections from one object or a list."""
    obj = unwrap(obj)
    if obj is None:
        return []
    if isinstance(obj, (list, tuple)):
        out = []
        for o in obj:
            o = unwrap(o)
            if o is not None and hasattr(o, 'values'):
                out.append(o)
        return out
    return [obj] if hasattr(obj, 'values') else []


def to_hourly_kwh(colls, label):
    """Sum collections into one hourly kWh list.

    Converts units, power to energy, sub-hourly to hourly. Returns
    (values, is_leap_year, first_collection) or (None, False, None).
    """
    if not colls:
        return None, False, None
    total = None
    leap = False
    for c in colls:
        hdr = c.header
        unit = str(hdr.unit)
        ukey = unit.strip().lower()
        try:
            dtype = str(hdr.data_type)
        except Exception:
            dtype = ''
        try:
            step = int(hdr.analysis_period.timestep)
            leap = leap or bool(hdr.analysis_period.is_leap_year)
        except Exception:
            step = 1
        vals = [float(v) for v in c.values]   # native floats, never foreign objects
        if ukey in ('kw', 'w', 'mw') or dtype.lower().startswith('power'):
            f = {'kw': 1.0, 'w': 1e-3, 'mw': 1e3}.get(ukey, 1.0)
            vals = [v * f / step for v in vals]
            NOTES.append('%s: %s in %s converted to kWh per interval'
                         % (label, dtype, unit))
        elif ukey in TO_KWH:
            if TO_KWH[ukey] != 1.0:
                vals = [v * TO_KWH[ukey] for v in vals]
                NOTES.append('%s: %s converted to kWh' % (label, unit))
        else:
            NOTES.append('%s: unit "%s" not recognised, assumed kWh'
                         % (label, unit))
        if step > 1:
            vals = [sum(vals[i:i + step]) for i in range(0, len(vals), step)]
            NOTES.append('%s: %d steps per hour summed to hourly'
                         % (label, step))
        if total is None:
            total = vals
        elif len(vals) == len(total):
            total = [a + b for a, b in zip(total, vals)]
        else:
            NOTES.append('%s: collection of %d values skipped, length '
                         'differs from %d' % (label, len(vals), len(total)))
    if len(colls) > 1:
        NOTES.append('%s: %d collections summed' % (label, len(colls)))
    return total, leap, colls[0]


# ------------------------------------------------------------ outputs
def header_dict(src_coll, name, unit, meta):
    ap = dict(src_coll.header.analysis_period.to_dict())
    ap["timestep"] = 1          # outputs are hourly even if the input was not
    return {"type": "Header",
            "data_type": {"type": "GenericDataType",
                          "data_type": "GenericType",
                          "name": name, "base_unit": unit},
            "unit": unit,
            "analysis_period": ap,
            "metadata": meta}


def make_hourly(src_coll, name, unit, values, meta):
    cls = type(src_coll)
    try:
        out = cls.from_dict({"type": "HourlyContinuous",
                             "header": header_dict(src_coll, name, unit, meta),
                             "values": list(values)})
        if hasattr(out, 'values') and len(out.values) == len(values):
            return out
        BUILD_LOG.append('%s: from_dict returned %s' % (name, type(out).__name__))
    except Exception as ex:
        BUILD_LOG.append('%s: from_dict failed, %s' % (name, ex))
    try:
        dup = src_coll.duplicate()
        if len(dup.values) != len(values):
            raise ValueError('source has %d values, output has %d'
                             % (len(dup.values), len(values)))
        dup.values = list(values)
        return dup
    except Exception as ex:
        BUILD_LOG.append('%s: duplicate fallback failed, %s' % (name, ex))
        return None


def make_monthly(src_coll, name, unit, values, meta):
    try:
        template = src_coll.total_monthly()
    except Exception as ex:
        BUILD_LOG.append('%s: total_monthly failed, %s' % (name, ex))
        return None
    cls = type(template)
    try:
        out = cls.from_dict({"type": "Monthly",
                             "header": header_dict(src_coll, name, unit, meta),
                             "values": list(values),
                             "datetimes": list(range(1, 13))})
        if hasattr(out, 'values') and len(out.values) == 12:
            return out
        BUILD_LOG.append('%s: from_dict returned %s' % (name, type(out).__name__))
    except Exception as ex:
        BUILD_LOG.append('%s: from_dict failed, %s' % (name, ex))
    try:
        template.values = list(values)
        return template
    except Exception as ex:
        BUILD_LOG.append('%s: template fallback failed, %s' % (name, ex))
        return None


# --------------------------------------------------------------- main
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

e, leap, elec = to_hourly_kwh(collections(_elec_data), 'electricity')
g, _, gas = to_hourly_kwh(collections(_gas_data), 'gas')

report = []
hourly_cost = hourly_rate = monthly_cost = monthly_peak = None
peak_times = []

MDY = list(MD)
if leap:
    MDY[1] = 29
NH = sum(MDY) * 24

if e is None:
    got = unwrap(_elec_data)
    report = ['_elec_data is not a Ladybug hourly collection.',
              'Received type: %s' % type(got).__name__,
              'Value preview: %s' % str(got)[:100],
              'If the preview says Object_N$N you are in the Python 3',
              'component. Use the IronPython 2 or legacy GhPython component,',
              'or switch to v2 which takes numbers via LB Deconstruct Data.']
elif len(e) != NH:
    report = ['_elec_data has %d hourly values, expected %d%s.'
              % (len(e), NH, ' (leap year)' if leap else ''),
              'Partial run periods are not supported. Rerun for a full',
              'calendar year with Hourly or Timestep reporting frequency.']
    if NOTES:
        report.append('Notes: ' + '; '.join(NOTES))
else:
    if g is not None and len(g) != NH:
        NOTES.append('gas: %d values, expected %d, gas ignored' % (len(g), NH))
        g = None
    if h0 == h1:
        NOTES.append('peak_hrs_ start equals end, no peak hours are priced')
    if min(e) < 0:
        NOTES.append('electricity has negative hours (export). Priced at the '
                     'import rate; net metering is not modelled')
    if leap:
        NOTES.append('leap year run, 8784 hours')

    st = []
    doy = 0
    for m in range(12):
        for d in range(MDY[m]):
            wd = (j1 + doy) % 7
            for h in range(24):
                st.append((m, d + 1, h, wd))
            doy += 1

    b = {'sp': [0., 0.], 'so': [0., 0.], 'wp': [0., 0.], 'wo': [0., 0.]}
    mc = [0.] * 12
    mpk = [[0.0, ''] for _ in range(12)]
    cost_h = [0.] * NH
    rate_h = [0.] * NH
    et = 0.
    for i in range(NH):
        m, d, h, wd = st[i]
        pk = (wd in PEAK_DAYS) and (h0 <= h < h1)
        s = (m + 1) in sm
        r = (ps if pk else op) if s else (pw if pk else op)
        k = ('s' if s else 'w') + ('p' if pk else 'o')
        c = e[i] * r
        rate_h[i] = r
        cost_h[i] = c
        b[k][0] += e[i]
        b[k][1] += c
        mc[m] += c
        et += c
        if e[i] > mpk[m][0]:
            mpk[m] = [float(e[i]), '%s %02d %02d:00-%02d:00' % (MN[m], d, h, h + 1)]

    gt = 0.
    gk = 0.
    if g is not None:
        for i in range(NH):
            c = g[i] * gr
            cost_h[i] += c
            mc[st[i][0]] += c
            gt += c
            gk += g[i]

    ek = sum(e)
    peaks = [float(p[0]) for p in mpk]
    dt_tot = 0.
    if dr > 0 or mch > 0:
        dt_tot = sum(peaks) * dm * dr + 12.0 * mch
        hcount = [MDY[m] * 24 for m in range(12)]
        for i in range(NH):
            m = st[i][0]
            cost_h[i] += (peaks[m] * dm * dr + mch) / hcount[m]

    mvals = [mc[m] + peaks[m] * dm * dr + mch for m in range(12)]
    peak_times = [p[1] for p in mpk]

    meta = {"source": "tou_cost 3.1.1",
            "rates": "sp %.4f wp %.4f op %.4f gas %.4f" % (ps, pw, op, gr)}
    hourly_cost = make_hourly(elec, 'Energy Cost', 'USD', cost_h, meta)
    hourly_rate = make_hourly(elec, 'Electric Rate', 'USD per kWh', rate_h, meta)
    monthly_cost = make_monthly(elec, 'Energy Cost', 'USD', mvals, meta)
    monthly_peak = make_monthly(elec, 'Peak Demand', 'kW', peaks, meta)

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
    status = []
    for nm, obj in (('hourly_cost', hourly_cost), ('hourly_rate', hourly_rate),
                    ('monthly_cost', monthly_cost), ('monthly_peak', monthly_peak)):
        status.append('%s %s' % (nm, 'ok' if obj is not None else 'FAILED'))
    report.append('Outputs: ' + ', '.join(status))
    if NOTES:
        report.append('Notes:')
        report.extend(['  ' + x for x in NOTES])
    if BUILD_LOG:
        report.append('Build log:')
        report.extend(['  ' + x for x in BUILD_LOG])

for line in report:
    print(line)
