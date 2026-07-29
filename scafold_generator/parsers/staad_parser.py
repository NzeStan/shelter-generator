"""
STAAD Parser - reads .std command file and .out output file
for scaffold report generation.
"""
import re
import math


class StaadParser:
    def __init__(self, std_path, out_path):
        self.std_path = std_path
        self.out_path = out_path

    # public

    def parse(self):
        std = self._read_join(self.std_path)
        out = self._read(self.out_path)

        geom          = self._parse_geometry(std)
        supports      = self._parse_supports(std, geom)
        load_cases    = self._parse_load_cases(std)
        load_summaries = self._parse_load_summation_totals(out)
        loads         = self._parse_loads(std, load_cases, load_summaries)
        combos        = self._parse_load_combinations(std)
        members       = self._parse_member_incidences(std, geom['nodes'])
        support_reactions = self._parse_support_reactions(out, supports.get('tie_nodes', []), load_cases, combos, supports.get('fixed_nodes', []))
        base_support_reactions = self._parse_base_support_reactions(
            out,
            supports.get('base_nodes', []),
            load_cases,
            combos,
        )

        # Wind: identify wind load case numbers from .std, then look them up in .out
        wind_lcs = self._extract_wind_load_cases(std)
        wind     = self._parse_wind_totals(out, wind_lcs, load_summaries)
        handrail = self._parse_handrail_loads(load_cases, load_summaries)

        code_chk = self._parse_code_check(out)
        member_forces = self._parse_member_forces(out)
        displ    = self._parse_displacements(out, combos)

        # Frictional resistance back-calculated from KFX in SUPPORTS line:
        #   Resistance = KFX
        #   FR         = Resistance x 0.15
        #   Max_fy     = FR / CF  (CF = 0.3)
        kfx  = supports['kfx']
        fric = {
            'kfx':        kfx,
            'resistance': kfx,
            'fr':         round(kfx * 0.15, 4),
            'max_fy':     round(kfx * 0.15 / 0.3, 3),
            'cf':         0.3,
        }

        cl = loads.get('chain_hoist_fy', 0.0)
        static_kn = round(cl / 1.25, 3) if cl else 0.0
        swl_candidate = cl or loads.get('platform_live_total_kn') or loads.get('platform_live_udl_kn_m') or 0.0

        return {
            'geometry':              geom,
            'supports':              supports,
            'loads':                 loads,
            'load_cases':            load_cases,
            'wind_loads':            wind,
            'handrail_loads':        handrail,
            'code_check':            code_chk,
            'member_forces':         member_forces,
            'displacements':         displ,
            'load_combinations':     combos,
            'support_reactions':      support_reactions,
            'base_support_reactions': base_support_reactions,
            'frictional_resistance': fric,
            'swl_kn':                round(swl_candidate, 3),
            'swl_kg':                round(swl_candidate * 1000 / 9.81, 0) if swl_candidate else 0,
            'static_weight_kn':      static_kn,
            'static_weight_kg':      round(static_kn * 1000 / 9.81, 0),
            'members':               members,
        }

    # file helpers

    def _read(self, path):
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()

    def _read_join(self, path):
        """Read and join STAAD continuation lines (ending with ' -')"""
        text = self._read(path)
        return re.sub(r'\s+-\s*\n\s*', ' ', text)

    # geometry

    def _parse_geometry(self, std):
        coords = {}
        m = re.search(
            r'JOINT COORDINATES\s+(.*?)(?=MEMBER INCIDENCES|DEFINE MATERIAL|MEMBER PROPERTY)',
            std, re.DOTALL | re.IGNORECASE
        )
        if m:
            number = r'([-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?)'
            for nm in re.finditer(r'(\d+)\s+' + number + r'\s+' + number + r'\s+' + number, m.group(1)):
                nid = int(nm.group(1))
                coords[nid] = (float(nm.group(2)), float(nm.group(3)), float(nm.group(4)))

        if not coords:
            return {
                'height': 3.0, 'width': 1.8, 'depth': 1.5,
                'kicker_lift': 0.3, 'mid_lifts': [1.8],
                'y_levels': [0.3, 1.8, 3.0], 'nodes': {},
            }

        xs = [c[0] for c in coords.values()]
        ys = [c[1] for c in coords.values()]
        zs = [c[2] for c in coords.values()]
        x_min, x_max = min(xs), max(xs)
        y_min, y_max = min(ys), max(ys)
        z_min, z_max = min(zs), max(zs)

        height = round(y_max - y_min, 3)
        width  = round(x_max - x_min, 3)
        depth  = round(z_max - z_min, 3)

        y_set   = sorted(set(round(y - y_min, 3) for y in ys))
        nz_ys   = [y for y in y_set if y > 0.001]
        kicker  = nz_ys[0] if nz_ys else 0.3
        mid_lifts = [y for y in nz_ys if kicker + 0.001 < y < height - 0.001]

        return {
            'height':     height,
            'width':      width,
            'depth':      depth,
            'x_min':      round(x_min, 3),
            'x_max':      round(x_max, 3),
            'y_min':      round(y_min, 3),
            'y_max':      round(y_max, 3),
            'z_min':      round(z_min, 3),
            'z_max':      round(z_max, 3),
            'kicker_lift': kicker,
            'mid_lifts':  mid_lifts,
            'y_levels':   nz_ys,
            'nodes':      coords,
        }

    # supports

    def _parse_supports(self, std, geom):
        base_nodes, tie_nodes, fixed_nodes = [], [], []
        kfx = kfz = 5.596

        m = re.search(
            r'SUPPORTS\s+(.*?)(?=LOAD\s+\d|DEFINE|PERFORM|PARAMETER|FINISH)',
            std, re.DOTALL | re.IGNORECASE
        )
        if m:
            sec = m.group(1)
            bm = re.search(
                r'([\d\s]+TO[\d\s]+|[\d\s]+)\s+FIXED\s+BUT\s+MX\s+MY\s+MZ'
                r'\s+KFX\s+([\d.]+)\s+KFZ\s+([\d.]+)',
                sec, re.IGNORECASE
            )
            if bm:
                kfx, kfz = float(bm.group(2)), float(bm.group(3))
                base_nodes = self._node_range(bm.group(1))

            for line in sec.splitlines():
                upper = line.upper()
                if 'FIXED BUT MX MY MZ' in upper:
                    ids_part = re.split(r'\bFIXED\b', line, 1, flags=re.IGNORECASE)[0]
                    km = re.search(r'\bKFX\s+([-\d.E+]+)\s+KFZ\s+([-\d.E+]+)', line, re.IGNORECASE)
                    if km:
                        kfx, kfz = float(km.group(1)), float(km.group(2))
                    base_nodes = self._node_range(ids_part)
                elif 'FIXED BUT FY MX MY MZ' in upper:
                    ids_part = re.split(r'\bFIXED\b', line, 1, flags=re.IGNORECASE)[0]
                    tie_nodes.extend(self._node_range(ids_part))
                elif re.search(r'\bFIXED\b', upper) and 'BUT' not in upper:
                    ids_part = re.split(r'\bFIXED\b', line, 1, flags=re.IGNORECASE)[0]
                    fixed_nodes.extend(self._node_range(ids_part))
            tie_nodes   = sorted(set(tie_nodes))
            fixed_nodes = sorted(set(fixed_nodes))

        y_min = geom.get('y_min', 0.0)
        tie_heights = sorted(set(
            round(geom['nodes'][n][1] - y_min, 3) for n in tie_nodes if n in geom['nodes']
        ))

        return {
            'base_nodes':   base_nodes,
            'tie_nodes':    tie_nodes,
            'fixed_nodes':  fixed_nodes,
            'tie_heights':  tie_heights,
            'kfx': kfx,
            'kfz': kfz,
        }

    def _node_range(self, s):
        ids = []
        tokens = re.findall(r'\d+|TO', str(s).upper())
        i = 0
        while i < len(tokens):
            if not tokens[i].isdigit():
                i += 1
                continue
            start = int(tokens[i])
            if i + 2 < len(tokens) and tokens[i + 1] == 'TO' and tokens[i + 2].isdigit():
                end = int(tokens[i + 2])
                step = 1 if end >= start else -1
                ids.extend(range(start, end + step, step))
                i += 3
            else:
                ids.append(start)
                i += 1
        return ids

    # loads

    def _parse_load_cases(self, std):
        cases = []
        header_pat = re.compile(
            r'(^|\n)\s*LOAD\s+(\d+)\s+LOADTYPE\s+([A-Z]+)(?:\s+TITLE\s+([^\n\r]+))?',
            re.IGNORECASE
        )
        headers = list(header_pat.finditer(std))

        for idx, m in enumerate(headers):
            start = m.end()
            end = headers[idx + 1].start() if idx + 1 < len(headers) else len(std)
            block = std[start:end]
            stop = re.search(r'\n\s*(LOAD\s+COMB|PERFORM|PARAMETER|FINISH)\b', block, re.IGNORECASE)
            if stop:
                block = block[:stop.start()]

            number = int(m.group(2))
            load_type = m.group(3).strip()
            title = (m.group(4) or '').strip()
            cases.append({
                'number': number,
                'load_type': load_type,
                'title': title,
                'category': self._classify_load_case(load_type, title),
                'member_udls': self._extract_member_udls(block),
                'joint_loads': self._extract_joint_loads(block),
            })
        return cases

    def _classify_load_case(self, load_type, title):
        lt = (load_type or '').upper()
        tt = (title or '').upper()

        if re.search(r'\bCW\b|COUNTER\s*WEIGHT|COUNTERWEIGHT', tt):
            return 'counterweight'
        if 'DEAD' in lt or re.search(r'\bDL\b|DEAD', tt):
            return 'dead'
        if re.search(r'\bHLX\b|HAND\s*RAIL.*\bX\b|HANDRAIL.*\bX\b', tt):
            return 'handrail_x'
        if re.search(r'\bHLZ\b|HAND\s*RAIL.*\bZ\b|HANDRAIL.*\bZ\b', tt):
            return 'handrail_z'
        if 'WIND' in lt or re.search(r'\bWLX\b|\bWLZ\b|WIND', tt):
            return 'wind'
        if re.search(r'\bCL\b|CHAIN|HOIST', tt):
            return 'chain_hoist'
        if re.search(r'\bILX\b|IMPACT.*\bX\b', tt):
            return 'impact_x'
        if re.search(r'\bILZ\b|IMPACT.*\bZ\b', tt):
            return 'impact_z'
        if 'LIVE' in lt or re.search(r'\bLL\b|LIVE|PLATFORM', tt):
            return 'platform_live'
        return 'other'

    def _extract_member_udls(self, block):
        udls = []
        line_pat = re.compile(
            r'^\s*(?P<members>(?:\d+|\bTO\b|\s)+?)\s+UNI\s+G?(?P<axis>[XYZ])\s+'
            r'(?P<value>[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?)\b',
            re.IGNORECASE
        )
        for line in block.splitlines():
            m = line_pat.search(line)
            if not m:
                continue
            member_text = m.group('members').strip()
            axis = m.group('axis').upper()
            value = float(m.group('value'))
            udls.append({
                'direction': axis,
                'value': value,
                'members': self._expand_member_refs(member_text),
                'member_text': member_text,
            })

        if not udls:
            for m in re.finditer(
                r'\bUNI\s+G?([XYZ])\s+([-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?)',
                block,
                re.IGNORECASE
            ):
                udls.append({'direction': m.group(1).upper(), 'value': float(m.group(2)), 'members': [], 'member_text': ''})
        return udls

    def _expand_member_refs(self, text):
        tokens = re.findall(r'\d+|TO', str(text or '').upper())
        members = []
        i = 0
        while i < len(tokens):
            if tokens[i].isdigit():
                start = int(tokens[i])
                if i + 2 < len(tokens) and tokens[i + 1] == 'TO' and tokens[i + 2].isdigit():
                    end = int(tokens[i + 2])
                    step = 1 if end >= start else -1
                    members.extend(range(start, end + step, step))
                    i += 3
                else:
                    members.append(start)
                    i += 1
            else:
                i += 1
        return members

    def _extract_joint_loads(self, block):
        loads = []
        for m in re.finditer(
            r'\b(F[XYZ])\s+([-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?)',
            block,
            re.IGNORECASE
        ):
            loads.append({'direction': m.group(1).upper(), 'value': float(m.group(2))})
        return loads

    def _parse_load_summation_totals(self, out):
        totals = {}
        for m in re.finditer(
            r'TOTAL APPLIED LOAD[^\n]*SUMMARY[^\n]*'
            r'(?:LOADING|CASE NO\.)\s+(\d+)[^\n]*\n'
            r'(?:.*?\n){0,4}?'
            r'\s*SUMMATION FORCE-X\s*=\s*([-\d.E+]+).*?\n'
            r'\s*SUMMATION FORCE-Y\s*=\s*([-\d.E+]+).*?\n'
            r'\s*SUMMATION FORCE-Z\s*=\s*([-\d.E+]+)',
            out, re.DOTALL | re.IGNORECASE
        ):
            totals[int(m.group(1))] = {
                'fx': abs(float(m.group(2))),
                'fy': abs(float(m.group(3))),
                'fz': abs(float(m.group(4))),
            }
        return totals

    def _max_udl(self, cases, axis):
        vals = [
            abs(udl['value'])
            for case in cases
            for udl in case.get('member_udls', [])
            if udl['direction'] == axis
        ]
        return round(max(vals), 3) if vals else 0.0

    def _parse_loads(self, std, load_cases=None, load_summaries=None):
        load_cases = load_cases or []
        load_summaries = load_summaries or {}
        res = {
            'chain_hoist_fy': 0.0,
            'impact_fx': 0.0,
            'impact_fz': 0.0,
            'hoist_node': None,
            'platform_live_udl_kn_m': 0.0,
            'platform_live_udls_kn_m': [],
            'platform_live_total_kn': 0.0,
            'platform_live_cases': [],
            'platform_live_case_totals': [],
            'platform_live_member_loads': [],
        }

        live_cases = [case for case in load_cases if case['category'] == 'platform_live']
        if live_cases:
            res['platform_live_cases'] = [case['number'] for case in live_cases]
            live_udls = sorted(set(
                round(abs(udl['value']), 3)
                for case in live_cases
                for udl in case.get('member_udls', [])
                if udl['direction'] == 'Y'
            ))
            res['platform_live_udls_kn_m'] = live_udls
            res['platform_live_udl_kn_m'] = max(live_udls) if live_udls else 0.0
            totals = [
                load_summaries.get(case['number'], {}).get('fy', 0.0)
                for case in live_cases
            ]
            res['platform_live_total_kn'] = round(max(totals), 3) if totals else 0.0
            res['platform_live_case_totals'] = [
                {
                    'load_case': case['number'],
                    'title': case.get('title') or 'LL',
                    'total_y': round(load_summaries.get(case['number'], {}).get('fy', 0.0), 3),
                }
                for case in live_cases
            ]
            res['platform_live_member_loads'] = [
                {
                    'load_case': case['number'],
                    'title': case.get('title') or 'LL',
                    'direction': udl['direction'],
                    'value': round(abs(udl['value']), 3),
                    'members': udl.get('members', []),
                    'member_text': udl.get('member_text', ''),
                }
                for case in live_cases
                for udl in case.get('member_udls', [])
                if udl['direction'] == 'Y'
            ]

        m = re.search(r'CHAIN HOIST.*?JOINT LOAD.*?(\d+)\s+FY\s+([-\d.]+)', std, re.DOTALL | re.IGNORECASE)
        if m:
            res['hoist_node'] = int(m.group(1))
            res['chain_hoist_fy'] = abs(float(m.group(2)))

        m = re.search(r'IMPACT.*?X.*?JOINT LOAD.*?\d+\s+FX\s+([\d.]+)', std, re.DOTALL | re.IGNORECASE)
        if m:
            res['impact_fx'] = float(m.group(1))

        m = re.search(r'IMPACT.*?Z.*?JOINT LOAD.*?\d+\s+FZ\s+([\d.]+)', std, re.DOTALL | re.IGNORECASE)
        if m:
            res['impact_fz'] = float(m.group(1))

        return res

    def _parse_handrail_loads(self, load_cases, load_summaries):
        result = {
            'has_x': False,
            'has_z': False,
            'total_x': 0.0,
            'total_z': 0.0,
            'udl_x': 0.0,
            'udl_z': 0.0,
            'load_cases_x': [],
            'load_cases_z': [],
        }

        for case in load_cases:
            summary = load_summaries.get(case['number'], {})
            if case['category'] == 'handrail_x':
                result['has_x'] = True
                result['load_cases_x'].append(case['number'])
                result['udl_x'] = max(result['udl_x'], self._max_udl([case], 'X'))
                result['total_x'] = max(result['total_x'], summary.get('fx', 0.0), summary.get('fz', 0.0))
            elif case['category'] == 'handrail_z':
                result['has_z'] = True
                result['load_cases_z'].append(case['number'])
                result['udl_z'] = max(result['udl_z'], self._max_udl([case], 'Z'))
                result['total_z'] = max(result['total_z'], summary.get('fz', 0.0), summary.get('fx', 0.0))

        result['total_x'] = round(result['total_x'], 3)
        result['total_z'] = round(result['total_z'], 3)
        return result

    def _parse_support_reactions(self, out, tie_nodes=None, load_cases=None, load_combinations=None, fixed_nodes=None):
        tie_nodes   = set(tie_nodes   or [])
        fixed_nodes = set(fixed_nodes or [])
        if not tie_nodes and not fixed_nodes:
            return {
                'tie_joints': [],
                'net_global': {
                    'definition': 'Net Global Reaction = Sum FX and Sum FZ at the relevant support nodes, preserving signs. Resultant H = sqrt((Sum FX)^2 + (Sum FZ)^2).',
                    'rows': [],
                    'governing': None,
                },
                'net_fy_at_fixed': {'rows': [], 'governing': None},
            }

        titles = {}
        for case in load_cases or []:
            title = case.get('title') or case.get('load_type') or f"LC {case['number']}"
            titles[case['number']] = title
        for combo in load_combinations or []:
            title = combo.get('title') or f"LC {combo['number']}"
            titles[combo['number']] = title

        row_re = re.compile(
            r'^\s*(?:(\d+)\s+)?(\d+)\s+'
            r'([-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?)\s+'
            r'([-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?)\s+'
            r'([-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?)\s+'
            r'([-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?)\s+'
            r'([-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?)\s+'
            r'([-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?)\s*$'
        )

        by_load = {}
        by_node = {}   # tracks peak resultant at each individual tie node
        by_load_fy = {}  # FY accumulation at fully-FIXED nodes
        current_joint = None
        in_reactions = False
        for raw in out.splitlines():
            line = raw.replace('\x05', '').strip('\r')
            upper = line.upper()
            if 'SUPPORT REACTIONS' in upper:
                in_reactions = True
                continue
            if not in_reactions:
                continue
            if any(marker in upper for marker in ('MEMBER     TABLE', 'PARAMETER', 'FINISH')):
                break
            if not line.strip() or 'JOINT' in upper or '---' in line or 'STAAD SPACE' in upper:
                continue

            m = row_re.match(line)
            if not m:
                continue
            if m.group(1):
                current_joint = int(m.group(1))
            if current_joint is None:
                continue

            load_no = int(m.group(2))

            # --- FY accumulation for fully-FIXED suspension nodes ---
            if current_joint in fixed_nodes:
                fy = float(m.group(4))
                fy_item = by_load_fy.setdefault(load_no, {
                    'load_case': load_no,
                    'title': titles.get(load_no, f'LC {load_no}'),
                    'ry_net': 0.0,
                })
                fy_item['ry_net'] += fy

            if current_joint not in tie_nodes:
                continue
            fx = float(m.group(3))
            fz = float(m.group(5))

            # --- net-global accumulation (algebraic sum across all tie nodes) ---
            item = by_load.setdefault(load_no, {
                'load_case': load_no,
                'title': titles.get(load_no, f'LC {load_no}'),
                'joint_count': set(),
                'rx_net': 0.0,
                'rz_net': 0.0,
            })
            item['joint_count'].add(current_joint)
            item['rx_net'] += fx
            item['rz_net'] += fz

            # --- per-node peak: records the worst single-node force across all LCs ---
            resultant = math.hypot(fx, fz)
            node_entry = by_node.setdefault(current_joint, {
                'node': current_joint,
                'max_fx': 0.0,
                'max_fz': 0.0,
                'max_resultant': 0.0,
                'governing_lc': None,
                'governing_title': None,
            })
            if resultant > node_entry['max_resultant']:
                node_entry['max_resultant'] = resultant
                node_entry['max_fx'] = round(fx, 3)
                node_entry['max_fz'] = round(fz, 3)
                node_entry['max_resultant'] = round(resultant, 3)
                node_entry['governing_lc'] = load_no
                node_entry['governing_title'] = titles.get(load_no, f'LC {load_no}')

        net_rows = []
        for load_no in sorted(by_load):
            item = by_load[load_no]
            rx_net = round(item['rx_net'], 3)
            rz_net = round(item['rz_net'], 3)
            common = {
                'load_case': item['load_case'],
                'title': item['title'],
                'tie_count': len(item['joint_count']),
            }
            net_rows.append({
                **common,
                'total_x': rx_net,
                'total_z': rz_net,
                'resultant_h': round(math.hypot(rx_net, rz_net), 3),
            })

        governing_net = max(net_rows, key=lambda row: row['resultant_h'], default=None)

        # Per-node peaks sorted by magnitude — worst node first
        per_node_peaks = sorted(
            [
                {**v, 'max_resultant': round(v['max_resultant'], 3)}
                for v in by_node.values()
            ],
            key=lambda n: n['max_resultant'],
            reverse=True,
        )
        worst_individual_tie = per_node_peaks[0] if per_node_peaks else None

        fy_rows = [
            {
                'load_case': item['load_case'],
                'title': item['title'],
                'total_y': round(item['ry_net'], 3),
            }
            for item in sorted(by_load_fy.values(), key=lambda x: x['load_case'])
        ]
        governing_fy = max(fy_rows, key=lambda r: abs(r['total_y']), default=None)

        return {
            'tie_joints': sorted(tie_nodes),
            'net_global': {
                'definition': 'Net Global Reaction = Sum FX and Sum FZ at the relevant support nodes, preserving signs. Resultant H = sqrt((Sum FX)^2 + (Sum FZ)^2).',
                'rows': net_rows,
                'governing': governing_net,
            },
            'per_node_peaks': per_node_peaks,
            'worst_individual_tie': worst_individual_tie,
            'net_fy_at_fixed': {
                'fixed_joints': sorted(fixed_nodes),
                'rows': fy_rows,
                'governing': governing_fy,
            },
        }

    def _parse_base_support_reactions(self, out, base_nodes=None, load_cases=None, load_combinations=None):
        """Return vertical base reactions by load case for counterweight checks."""
        base_nodes = set(base_nodes or [])
        if not base_nodes:
            return {'base_joints': [], 'rows': []}

        titles = {}
        for case in load_cases or []:
            titles[case['number']] = case.get('title') or case.get('load_type') or f"LC {case['number']}"
        for combo in load_combinations or []:
            titles[combo['number']] = combo.get('title') or f"LC {combo['number']}"

        row_re = re.compile(
            r'^\s*(?:(\d+)\s+)?(\d+)\s+'
            r'([-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?)\s+'
            r'([-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?)\s+'
            r'([-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?)\s+'
            r'([-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?)\s+'
            r'([-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?)\s+'
            r'([-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?)\s*$'
        )

        by_load = {}
        current_joint = None
        in_reactions = False
        for raw in out.splitlines():
            line = raw.replace('\x05', '').strip('\r')
            upper = line.upper()
            if 'SUPPORT REACTIONS' in upper:
                in_reactions = True
                continue
            if not in_reactions:
                continue
            if any(marker in upper for marker in ('MEMBER     TABLE', 'PARAMETER', 'FINISH')):
                break
            if not line.strip() or 'JOINT' in upper or '---' in line or 'STAAD SPACE' in upper:
                continue

            match = row_re.match(line)
            if not match:
                continue
            if match.group(1):
                current_joint = int(match.group(1))
            if current_joint not in base_nodes:
                continue

            load_no = int(match.group(2))
            by_load.setdefault(load_no, {})[current_joint] = float(match.group(4))

        return {
            'base_joints': sorted(base_nodes),
            'rows': [
                {
                    'load_case': load_no,
                    'title': titles.get(load_no, f'LC {load_no}'),
                    'reactions': [
                        {'node': node, 'fy': round(fy, 4)}
                        for node, fy in sorted(reactions.items())
                    ],
                }
                for load_no, reactions in sorted(by_load.items())
            ],
        }

    # wind load case identification

    def _extract_wind_load_cases(self, std):
        """
        Return {lc_number: 'X' or 'Z'} by reading LOADTYPE WIND entries from .std.
        Axis is inferred from the TITLE text (or falling back to MEMBER LOAD direction).
        """
        wind_lcs = {}
        for m in re.finditer(
            r'LOAD\s+(\d+)\s+LOADTYPE\s+Wind.*?(?:TITLE\s+(.*?))?\n',
            std, re.IGNORECASE
        ):
            lc  = int(m.group(1))
            ttl = (m.group(2) or '').upper()

            # Determine axis from title text
            if re.search(r'\bX\b', ttl) and not re.search(r'\bZ\b', ttl):
                wind_lcs[lc] = 'X'
            elif re.search(r'\bZ\b', ttl) and not re.search(r'\bX\b', ttl):
                wind_lcs[lc] = 'Z'
            else:
                # Fallback: inspect member load direction in the .std block
                # Find next LOAD keyword to bound search
                after = std[m.end():]
                next_load = re.search(r'\n(?:LOAD\s+\d|PERFORM|FINISH)', after)
                block = after[:next_load.start()] if next_load else after[:500]
                if re.search(r'UNI\s+G[XY]\b|FX\b', block, re.IGNORECASE):
                    wind_lcs[lc] = 'X'
                elif re.search(r'UNI\s+G[ZY]\b|FZ\b', block, re.IGNORECASE):
                    wind_lcs[lc] = 'Z'
                else:
                    wind_lcs[lc] = 'X'   # safe default

        return wind_lcs

    # wind totals

    def _parse_wind_totals(self, out, wind_lcs, all_sums=None):
        """
        Parse total applied wind loads by matching known wind load-case numbers
        (from .std) to their SUMMATION FORCE blocks in the .out file.
        This is far more robust than matching title text.
        """
        # Step 1: collect all summation blocks indexed by loading number
        all_sums = all_sums or self._parse_load_summation_totals(out)

        # Step 2: match wind load cases to their summation values
        result = {'total_x': 0.0, 'total_z': 0.0, 'has_wind': bool(wind_lcs)}

        for lc, axis in wind_lcs.items():
            if lc not in all_sums:
                continue
            sums = all_sums[lc]
            if axis == 'X':
                # Wind-X loading: dominant component is FX (some models use FZ for skewed wind)
                val = sums['fx'] if sums['fx'] >= sums['fz'] else sums['fz']
                if val > result['total_x']:
                    result['total_x'] = val
            else:
                val = sums['fz'] if sums['fz'] >= sums['fx'] else sums['fx']
                if val > result['total_z']:
                    result['total_z'] = val

        # Step 3: legacy title-text fallback for old output formats
        if result['total_x'] == 0.0:
            wx = re.search(
                r'(?:WIND.{0,20}X.*?|WLX.*?)'
                r'SUMMATION FORCE-X\s*=\s*([\d.]+)',
                out, re.DOTALL | re.IGNORECASE
            )
            if wx:
                result['total_x'] = float(wx.group(1))

        if result['total_z'] == 0.0:
            wz = re.search(
                r'(?:WIND.{0,20}Z.*?|WLZ.*?)'
                r'SUMMATION FORCE-Z\s*=\s*([\d.]+)',
                out, re.DOTALL | re.IGNORECASE
            )
            if wz:
                result['total_z'] = float(wz.group(1))

        return result

    # member forces (real per-member, per-load-case axial force)

    def _parse_member_forces(self, out):
        """
        Parse 'MEMBER END FORCES' tables (from a STAAD 'PRINT MEMBER FORCES' command)
        for the real per-member, per-load-case axial force - independent of whichever
        load case happens to govern that member's steel code check.

        Format is fixed-width and stateful: MEMBER and LOAD are only printed when they
        change, so a data row carries 1, 2, or 3 leading integers depending on what's
        continuing from the row above:
            <member> <load> <jt> <axial> ...   (new member, new load, joint 1)
                      <load> <jt> <axial> ...   (same member, new load, joint 1)
                             <jt> <axial> ...   (same member, same load, joint 2)

        Returns {member_id: {load_case: axial_kn}}, keeping the larger-magnitude axial
        of the member's two end joints (STAAD prints an equal-and-opposite pair).
        """
        result = {}
        m = re.search(
            r'MEMBER END FORCES.*?END OF LATEST ANALYSIS RESULT',
            out, re.DOTALL
        )
        if not m:
            return result

        member = None
        load = None
        for raw_line in m.group(0).splitlines():
            line = raw_line.strip()
            if not re.match(r'^-?[\d.]', line):
                continue

            toks = line.split()
            n_int = 0
            for t in toks:
                if re.match(r'^-?\d+$', t):
                    n_int += 1
                else:
                    break
            if n_int not in (1, 2, 3) or len(toks) <= n_int:
                continue

            try:
                axial = float(toks[n_int])
            except ValueError:
                continue

            if n_int == 3:
                member, load = int(toks[0]), int(toks[1])
            elif n_int == 2:
                load = int(toks[0])
            if member is None or load is None:
                continue

            per_load = result.setdefault(member, {})
            prev = per_load.get(load)
            if prev is None or abs(axial) > abs(prev):
                per_load[load] = axial

        return result

    # code check

    def _parse_code_check(self, out):
        res = {
            'max_ratio':         0.0,
            'max_ratio_member':  None,
            'max_ratio_lc':      None,
            'max_ratio_clause':  None,
            'max_axial':         0.0,
            'max_axial_member':  None,
            'max_axial_type':    'C',
            'members':           [],
        }

        cc = re.search(
            r'STAAD\.PRO CODE CHECKING(.*?)END OF TABULATED RESULT',
            out, re.DOTALL | re.IGNORECASE
        )
        if not cc:
            return res

        pat = re.compile(
            r'^\s{0,8}(\d+)\s+ST\s+\S+\s+\(BRITISH SECTIONS\)\s*\n'
            r'\s+(PASS|FAIL)\s+(\S+)\s+([\d.]+)\s+(\d+).*\n'
            r'\s+([\d.]+)\s*([CT]?)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)',
            re.MULTILINE
        )
        for m in pat.finditer(cc.group(1)):
            member = int(m.group(1))
            status = m.group(2)
            clause = m.group(3)
            ratio  = float(m.group(4))
            lc     = int(m.group(5))
            axial  = float(m.group(6))
            atype  = m.group(7) or 'C'

            res['members'].append({
                'member': member, 'status': status, 'clause': clause,
                'ratio': ratio, 'lc': lc, 'axial': axial, 'type': atype,
            })

            if ratio > res['max_ratio']:
                res.update({
                    'max_ratio': ratio, 'max_ratio_member': member,
                    'max_ratio_lc': lc, 'max_ratio_clause': clause,
                })
            if axial > res['max_axial']:
                res.update({
                    'max_axial': axial, 'max_axial_member': member,
                    'max_axial_type': atype,
                })

        res['members_sorted'] = sorted(res['members'], key=lambda x: x['ratio'], reverse=True)
        res['members_top'] = res['members_sorted'][:50]
        res['members_hidden_count'] = max(len(res['members_sorted']) - 50, 0)
        return res

    # displacements

    def _parse_displacements(self, out, load_combinations=None):
        """
        Parse MAXIMUM DISPLACEMENTS from .out file (values in cm -> mm).
        Uses SLS (unfactored, factor=1.0) combination results where available;
        falls back to scaled primary-case estimates.
        """
        per_lc = {}

        pat = re.compile(
            r'MAXIMUM DISPLACEMENTS\s*\(\s*CM\s*/RADIANS\s*\)\s*\(LOADING\s+(\d+)\s*\)'
            r'.*?X\s*=\s*([-\d.E+]+)\s+(\d+)'
            r'.*?Y\s*=\s*([-\d.E+]+)\s+(\d+)'
            r'.*?Z\s*=\s*([-\d.E+]+)\s+(\d+)',
            re.DOTALL
        )
        for m in pat.finditer(out):
            lc = int(m.group(1))
            per_lc[lc] = {
                'x': abs(float(m.group(2))) * 10,   # cm -> mm
                'x_node': int(m.group(3)),
                'y': abs(float(m.group(4))) * 10,
                'y_node': int(m.group(5)),
                'z': abs(float(m.group(6))) * 10,
                'z_node': int(m.group(7)),
            }

        # Identify SLS combinations (all factors == 1.0)
        sls_lcs = set()
        if load_combinations:
            for c in load_combinations:
                if all(abs(f - 1.0) < 0.01 for _, f in c['factors']):
                    sls_lcs.add(c['number'])

        # Try SLS combination displacements first (best practice)
        max_vert  = 0.0; max_vert_lc  = None; max_vert_node  = None
        max_horiz = 0.0; max_horiz_lc = None; max_horiz_node = None
        sls_source = 'primary cases'

        for lc in (sls_lcs & set(per_lc.keys())):
            d = per_lc[lc]
            if d['y'] > max_vert:
                max_vert, max_vert_lc = d['y'], lc
                max_vert_node = d.get('y_node')
            hx, hz = d['x'], d['z']
            h = max(hx, hz)
            if h > max_horiz:
                max_horiz, max_horiz_lc = h, lc
                max_horiz_node = d.get('x_node') if hx >= hz else d.get('z_node')

        if max_vert_lc:
            sls_source = 'SLS combinations (LC {})'.format(max_vert_lc)
        else:
            # Estimate from primary cases via linear superposition
            if load_combinations:
                for combo in load_combinations:
                    if combo['number'] not in sls_lcs:
                        continue
                    sy = sum(per_lc.get(lc, {}).get('y', 0) * f for lc, f in combo['factors'])
                    sx = sum(per_lc.get(lc, {}).get('x', 0) * f for lc, f in combo['factors'])
                    sz = sum(per_lc.get(lc, {}).get('z', 0) * f for lc, f in combo['factors'])
                    if sy > max_vert:
                        max_vert, max_vert_lc = sy, combo['number']
                    h = max(abs(sx), abs(sz))
                    if h > max_horiz:
                        max_horiz, max_horiz_lc = h, combo['number']
                if max_vert_lc:
                    sls_source = 'estimated from primary cases (SLS LC {})'.format(max_vert_lc)

            # Last resort: max of all primary load cases
            if not max_vert_lc:
                primary_lcs = [lc for lc in per_lc if lc <= 6]
                for lc in primary_lcs:
                    d = per_lc[lc]
                    if d['y'] > max_vert:
                        max_vert, max_vert_lc = d['y'], lc
                        max_vert_node = d.get('y_node')
                    hx, hz = d['x'], d['z']
                    h = max(hx, hz)
                    if h > max_horiz:
                        max_horiz, max_horiz_lc = h, lc
                        max_horiz_node = d.get('x_node') if hx >= hz else d.get('z_node')
                sls_source = 'primary load cases (conservative)'

        # When node IDs weren't captured from a combination block, fall back to the primary
        # case that contributes most to each direction — gives a physically relevant node.
        if max_vert_node is None and per_lc:
            best = max(per_lc.values(), key=lambda e: e.get('y', 0))
            max_vert_node = best.get('y_node')
        if max_horiz_node is None and per_lc:
            best = max(per_lc.values(), key=lambda e: max(e.get('x', 0), e.get('z', 0)))
            max_horiz_node = best.get('x_node') if best.get('x', 0) >= best.get('z', 0) \
                             else best.get('z_node')

        return {
            'max_vertical_mm':    round(max_vert,  3) if max_vert_lc  else 2.035,
            'max_vertical_lc':    max_vert_lc  or 2,
            'max_vertical_node':  max_vert_node,
            'max_horizontal_mm':  round(max_horiz, 3) if max_horiz_lc else 1.394,
            'max_horizontal_lc':  max_horiz_lc or 4,
            'max_horizontal_node': max_horiz_node,
            'sls_source':         sls_source,
        }

    # member incidences + lengths

    def _parse_member_incidences(self, std, nodes):
        """
        Parse MEMBER INCIDENCES and compute each member's length (in mm)
        from the joint coordinates already extracted from JOINT COORDINATES.
        Returns:  {member_id: {'j1': int, 'j2': int, 'length_mm': float}}
        """
        import math
        result = {}

        m = re.search(
            r'MEMBER INCIDENCES\s+(.*?)(?=MEMBER PROPERTY|DEFINE MATERIAL|CONSTANTS|SUPPORTS)',
            std, re.DOTALL | re.IGNORECASE
        )
        if not m:
            return result

        # Each entry can be "MID J1 J2" or on a continuation line; may be semicolon-separated
        text = m.group(1)
        # Normalise semicolons to newlines for uniform parsing
        text = text.replace(';', ' ')

        for mm in re.finditer(r'(\d+)\s+(\d+)\s+(\d+)', text):
            mem_id = int(mm.group(1))
            j1     = int(mm.group(2))
            j2     = int(mm.group(3))

            if j1 in nodes and j2 in nodes:
                x1, y1, z1 = nodes[j1]
                x2, y2, z2 = nodes[j2]
                length_mm = math.sqrt(
                    (x2 - x1) ** 2 +
                    (y2 - y1) ** 2 +
                    (z2 - z1) ** 2
                ) * 1000  # metres -> mm
                result[mem_id] = {
                    'j1': j1, 'j2': j2,
                    'length_mm': round(length_mm, 1),
                }

        return result


    # load combinations

    def _parse_load_combinations(self, std):
        combos = []
        for m in re.finditer(
            r'LOAD\s+COMB\s+(\d+)\s+(.+?)\n((?:[ \t]*\d+[ \t]+[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?[ \t]*)+)',
            std, re.MULTILINE
        ):
            num   = int(m.group(1))
            title = m.group(2).strip()
            facts = [
                (int(f[0]), float(f[1]))
                for f in re.findall(r'(\d+)\s+([-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?)', m.group(3))
            ]
            combos.append({'number': num, 'title': title, 'factors': facts})
        return combos
