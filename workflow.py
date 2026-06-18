import csv
import json
import math
import os
from collections import defaultdict, Counter
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(__file__).parent / 'data'
OUT_DIR = Path(__file__).parent / 'outputs'
OUT_DIR.mkdir(exist_ok=True)

PRICING = {
    'GPT-5.5': {'input': 5.0, 'output': 30.0},
    'GPT-5.4': {'input': 2.5, 'output': 15.0},
    'GPT-5.4 mini': {'input': 0.75, 'output': 4.5},
    'text-embedding-3-small': {'input': 0.02, 'output': 0.0},
    'Claude Sonnet 4.6': {'input': 3.0, 'output': 15.0},
    'Claude Haiku 4.5': {'input': 1.0, 'output': 5.0},
}

STAGE_MODEL = {
    'memory_retrieval': 'text-embedding-3-small',
    'account_review': 'Claude Haiku 4.5',
    'prioritization': 'GPT-5.4 mini',
    'inbound_issue_handling': 'Claude Haiku 4.5',
    'checkin_support': 'GPT-5.4 mini',
    'quality_review': 'GPT-5.4 mini',
    'intervention_planning': 'Claude Sonnet 4.6',
    'routing': 'Claude Haiku 4.5',
    'evaluation': 'GPT-5.4 mini',
}


SCENARIO_PARAMS = {
    'base': {
        'renewal_boost': 25,
        'ticket_weight': 3,
        'nps_weight': 4,
        'usage_multiplier': 1.0,
    },
    'renewal_risk': {
        'renewal_boost': 45,
        'ticket_weight': 3,
        'nps_weight': 4,
        'usage_multiplier': 1.0,
    },
    'support_spike': {
        'renewal_boost': 25,
        'ticket_weight': 8,
        'nps_weight': 4,
        'usage_multiplier': 1.0,
    },
    'quality_batch': {
        'renewal_boost': 25,
        'ticket_weight': 3,
        'nps_weight': 6,
        'usage_multiplier': 1.0,
    },
    'segment_decline': {
        'renewal_boost': 25,
        'ticket_weight': 3,
        'nps_weight': 4,
        'usage_multiplier': 2.0,
    },
}

PROMPTS = {
    'account_review': 'Review account health signals, usage trend, tickets, renewal date, NPS, and notes. Return risk score, drivers, opportunity flags, and recommended next action.',
    'prioritization': 'Rank accounts by action urgency and business impact. Prefer imminent renewals, sharp health decline, high contract value, negative sentiment, and open blockers.',
    'inbound_issue_handling': 'Classify each support issue as immediate resolution, scheduled follow up, or escalation. Explain reason, owner path, and customer response guidance.',
    'checkin_support': 'Prepare structured customer check in notes using account context, prior call notes, open risks, agenda, success criteria, and follow up actions.',
    'quality_review': 'Evaluate customer facing draft against quality standards. Flag missing context, unclear action, risk mismatch, and tone problems. Suggest corrected version.',
    'intervention_planning': 'Detect account segment decline and design a corrective intervention with target cohort, actions, owner, metric, and measurement window.',
    'routing': 'Produce the final work queue with resolution route, follow up date, escalation reason, and CSM or support owner.',
    'evaluation': 'Check output completeness, route validity, and whether every high risk item has an owner and next step.'
}


def read_csv(name):
    with open(DATA_DIR / name, newline='') as f:
        return list(csv.DictReader(f))


def parse_date(value):
    return datetime.strptime(value, '%Y-%m-%d') if value else None


def token_count(text):
    return max(1, math.ceil(len(str(text).split()) * 1.33))


def record_usage(stage, input_obj, output_obj, usage):
    model = STAGE_MODEL[stage]
    in_tokens = token_count(json.dumps(input_obj, default=str)) + token_count(PROMPTS.get(stage, ''))
    out_tokens = token_count(json.dumps(output_obj, default=str))
    price = PRICING[model]
    cost = (in_tokens / 1_000_000) * price['input'] + (out_tokens / 1_000_000) * price['output']
    usage.append({
        'stage': stage,
        'model': model,
        'input_tokens': in_tokens,
        'output_tokens': out_tokens,
        'cost_usd': round(cost, 8)
    })


def build_context():
    accounts = read_csv('accounts.csv')
    usage = read_csv('usage_events.csv')
    tickets = read_csv('support_tickets.csv')
    calls = read_csv('call_notes.csv')
    checkins = read_csv('scheduled_checkins.csv')
    outputs = read_csv('junior_outputs.csv')
    standards = {r['standard_id']: r for r in read_csv('quality_standards.csv')}

    usage_by_account = defaultdict(list)
    for r in usage:
        usage_by_account[r['account_id']].append(r)
    tickets_by_account = defaultdict(list)
    for r in tickets:
        tickets_by_account[r['account_id']].append(r)
    calls_by_account = defaultdict(list)
    for r in calls:
        calls_by_account[r['account_id']].append(r)
    return accounts, usage_by_account, tickets_by_account, calls_by_account, checkins, outputs, standards


def risk_score(account, tickets, usage_rows, scenario_params):
    health = int(account['current_health_score'])
    previous = int(account['previous_health_score'])
    renewal = parse_date(account['renewal_date'])
    today = datetime(2026, 5, 1)
    days_to_renewal = (renewal - today).days if renewal else 999
    score = 100 - health
    score += max(0, previous - health) * 1.2
    score += {'declining': 18, 'flat': 7, 'growing': -5}.get(account['product_usage_trend'], 0) * scenario_params['usage_multiplier']
    score += int(account['support_ticket_count_30d']) * scenario_params['ticket_weight']
    score += max(0, 7 - int(account['nps_score'])) * scenario_params['nps_weight']
    if days_to_renewal <= 45:
        score += scenario_params['renewal_boost']
    elif days_to_renewal <= 90:
        score += round(scenario_params['renewal_boost'] * 0.48, 1)
    if any(t['severity'].lower() == 'high' for t in tickets):
        score += 20
    if account['expansion_signal'].lower() == 'high':
        score -= 8
    return max(0, round(score, 1))


def review_accounts(accounts, usage_by_account, tickets_by_account, usage_log, scenario_params):
    reviews = []
    for a in accounts:
        tickets = tickets_by_account[a['account_id']]
        usage_rows = usage_by_account[a['account_id']]
        score = risk_score(a, tickets, usage_rows, scenario_params)
        risk_level = 'critical' if score >= 90 else 'high' if score >= 70 else 'medium' if score >= 45 else 'low'
        drivers = []
        if int(a['current_health_score']) < 65: drivers.append('low health score')
        if int(a['previous_health_score']) - int(a['current_health_score']) >= 10: drivers.append('health decline')
        if a['product_usage_trend'] == 'declining': drivers.append('declining usage')
        if int(a['support_ticket_count_30d']) >= 5: drivers.append('ticket load')
        if int(a['nps_score']) <= 4: drivers.append('low NPS')
        if any(t['severity'] == 'High' for t in tickets): drivers.append('high severity open issue')
        opportunity = a['expansion_signal'] in ('medium', 'high') and risk_level in ('low', 'medium')
        next_action = 'escalate recovery plan' if risk_level == 'critical' else 'CSM follow up within 2 business days' if risk_level == 'high' else 'prepare expansion conversation' if opportunity else 'monitor'
        reviews.append({
            'account_id': a['account_id'], 'account_name': a['account_name'], 'segment': a['segment'],
            'contract_value': int(a['contract_value']), 'risk_score': score, 'risk_level': risk_level,
            'drivers': drivers, 'expansion_opportunity': opportunity, 'recommended_next_action': next_action,
            'owner': a['csm_owner']
        })
    record_usage('account_review', {'accounts': accounts[:5], 'usage_sample': list(usage_by_account.items())[:2]}, reviews, usage_log)
    return reviews


def prioritize(reviews, usage_log):
    ranked = sorted(reviews, key=lambda r: (r['risk_score'], r['contract_value']), reverse=True)
    top = ranked[:10]
    record_usage('prioritization', reviews, top, usage_log)
    return top


def handle_tickets(tickets_by_account, account_lookup, usage_log):
    routed = []
    for acct_id, tickets in tickets_by_account.items():
        a = account_lookup[acct_id]
        for t in tickets:
            renewal_days = (parse_date(a['renewal_date']) - datetime(2026, 5, 1)).days
            if t['severity'] == 'High' or 'blocked' in t['issue_summary'].lower() or renewal_days <= 45:
                route = 'escalation'
                owner = 'Support engineering plus CSM'
            elif t['customer_sentiment'] in ('negative', 'frustrated', 'concerned'):
                route = 'scheduled follow up'
                owner = a['csm_owner']
            else:
                route = 'immediate resolution'
                owner = 'Frontline support'
            routed.append({
                'ticket_id': t['ticket_id'], 'account_id': acct_id, 'account_name': a['account_name'],
                'issue_summary': t['issue_summary'], 'severity': t['severity'], 'sentiment': t['customer_sentiment'],
                'route': route, 'owner': owner,
                'customer_response': f"Acknowledge the issue, confirm current owner is {owner}, and provide next update timing."
            })
    record_usage('inbound_issue_handling', [v for rows in tickets_by_account.values() for v in rows], routed, usage_log)
    return routed


def prepare_checkins(checkins, account_lookup, calls_by_account, ticket_routes, usage_log):
    routes_by_acct = defaultdict(list)
    for r in ticket_routes:
        routes_by_acct[r['account_id']].append(r)
    plans = []
    for c in checkins:
        a = account_lookup[c['account_id']]
        prior = calls_by_account[c['account_id']][-1] if calls_by_account[c['account_id']] else {}
        routes = routes_by_acct[c['account_id']]
        plan = {
            'checkin_id': c['checkin_id'], 'account_name': a['account_name'], 'date': c['scheduled_date'],
            'priority': c['priority'], 'agenda': c['topics_to_cover'],
            'opening_context': prior.get('summary', a['notes']),
            'customer_goal': prior.get('customer_goal', 'Confirm current business outcome and blockers'),
            'known_risks': [prior.get('risk_or_blocker')] + [r['issue_summary'] for r in routes if r['route'] == 'escalation'],
            'recommended_follow_up': prior.get('follow_up_items', 'Document owner, next step, and date after call')
        }
        plans.append(plan)
    record_usage('checkin_support', {'checkins': checkins, 'calls': dict(calls_by_account)}, plans, usage_log)
    return plans


def review_outputs(outputs, standards, account_lookup, usage_log):
    reviewed = []
    for o in outputs:
        draft = o['draft_text']
        standards_used = [standards[s] for s in o['quality_standard_ids'].split(';') if s in standards]
        findings = []
        if account_lookup[o['account_id']]['account_name'] not in draft:
            findings.append('Missing account-specific reference')
        if not any(word in draft.lower() for word in ['by ', 'next', 'today', 'tomorrow', 'date', 'plan']):
            findings.append('No concrete timing or owner')
        if len(draft.split()) < 25:
            findings.append('Too generic for customer-facing use')
        status = 'needs revision' if findings else 'approved'
        revised = f"{account_lookup[o['account_id']]['account_name']}: We see {account_lookup[o['account_id']]['notes']}. Next step: assign the owner, confirm timing, and send a measurable update tied to {o['intended_customer_action'].lower()}."
        reviewed.append({
            'output_id': o['output_id'], 'account_id': o['account_id'], 'output_type': o['output_type'],
            'status': status, 'findings': findings, 'standards_checked': [s['standard_id'] for s in standards_used],
            'revised_version': revised
        })
    record_usage('quality_review', outputs, reviewed, usage_log)
    return reviewed


def plan_interventions(reviews, account_lookup, usage_log):
    declining = [r for r in reviews if 'declining usage' in r['drivers']]
    by_segment = Counter(account_lookup[r['account_id']]['segment'] for r in declining)
    target_segment = by_segment.most_common(1)[0][0] if by_segment else 'At-risk accounts'
    cohort = [r for r in declining if account_lookup[r['account_id']]['segment'] == target_segment]
    plan = {
        'target_segment': target_segment,
        'cohort_account_ids': [r['account_id'] for r in cohort],
        'problem_pattern': 'Declining usage is co-occurring with health score deterioration and upcoming renewal risk.',
        'intervention': 'Two week recovery sprint: usage diagnosis, executive status update, admin enablement, and weekly success metric review.',
        'owners': ['CSM owner', 'Support engineering for blockers', 'CS ops for reporting'],
        'success_metrics': ['active users stabilized or up 10 percent', 'open high severity tickets reduced', 'health score stops declining'],
        'measurement_window_days': 14
    }
    record_usage('intervention_planning', declining, plan, usage_log)
    return plan


def final_route(top_accounts, ticket_routes, checkin_plans, quality_reviews, intervention, usage_log):
    queue = []
    for r in top_accounts:
        queue.append({'type': 'account action', 'account_id': r['account_id'], 'priority': r['risk_level'], 'route': r['recommended_next_action'], 'owner': r['owner']})
    for r in ticket_routes:
        queue.append({'type': 'ticket', 'account_id': r['account_id'], 'priority': r['severity'], 'route': r['route'], 'owner': r['owner']})
    for q in quality_reviews:
        if q['status'] != 'approved':
            queue.append({'type': 'quality correction', 'account_id': q['account_id'], 'priority': 'medium', 'route': 'revise before send', 'owner': 'CSM manager'})
    queue.append({'type': 'segment intervention', 'account_id': ','.join(intervention['cohort_account_ids']), 'priority': 'high', 'route': intervention['intervention'], 'owner': 'CS ops lead'})
    record_usage('routing', {'top': top_accounts, 'tickets': ticket_routes, 'quality': quality_reviews}, queue, usage_log)
    return queue


def evaluate(queue, usage_log):
    missing_owner = [i for i in queue if not i.get('owner')]
    unresolved_high = [i for i in queue if i.get('priority') in ('critical','High','high') and i.get('route') in ('monitor','')]
    result = {'passed': not missing_owner and not unresolved_high, 'missing_owner_count': len(missing_owner), 'unresolved_high_count': len(unresolved_high), 'queue_items_checked': len(queue)}
    record_usage('evaluation', queue, result, usage_log)
    return result


def run_workflow(run_id='base'):
    usage_log = []
    scenario_params = SCENARIO_PARAMS.get(run_id, SCENARIO_PARAMS['base'])
    accounts, usage_by_account, tickets_by_account, calls_by_account, checkins, outputs, standards = build_context()
    account_lookup = {a['account_id']: a for a in accounts}
    record_usage('memory_retrieval', {'data_files': ['accounts','usage','tickets','calls','checkins','outputs','standards']}, {'records_loaded': sum([len(accounts), sum(map(len, usage_by_account.values())), sum(map(len, tickets_by_account.values())), len(checkins), len(outputs), len(standards)])}, usage_log)
    reviews = review_accounts(accounts, usage_by_account, tickets_by_account, usage_log, scenario_params)
    top = prioritize(reviews, usage_log)
    ticket_routes = handle_tickets(tickets_by_account, account_lookup, usage_log)
    checkin_plans = prepare_checkins(checkins, account_lookup, calls_by_account, ticket_routes, usage_log)
    quality_reviews = review_outputs(outputs, standards, account_lookup, usage_log)
    intervention = plan_interventions(reviews, account_lookup, usage_log)
    queue = final_route(top, ticket_routes, checkin_plans, quality_reviews, intervention, usage_log)
    eval_result = evaluate(queue, usage_log)
    total_cost = round(sum(u['cost_usd'] for u in usage_log), 8)
    result = {
        'run_id': run_id,
        'generated_at': '2026-05-01T09:00:00',
        'scenario_params': scenario_params,
        'account_reviews': reviews,
        'priority_accounts': top,
        'ticket_routes': ticket_routes,
        'checkin_plans': checkin_plans,
        'quality_reviews': quality_reviews,
        'intervention_plan': intervention,
        'work_queue': queue,
        'evaluation': eval_result,
        'token_usage': usage_log,
        'measured_total_cost_usd': total_cost
    }
    out = OUT_DIR / f'run_{run_id}.json'
    out.write_text(json.dumps(result, indent=2))
    return result


def write_summaries(results):
    stage_rows = defaultdict(lambda: {'runs':0,'input_tokens':0,'output_tokens':0,'cost_usd':0.0,'model':''})
    for res in results:
        for u in res['token_usage']:
            row = stage_rows[u['stage']]
            row['runs'] += 1
            row['input_tokens'] += u['input_tokens']
            row['output_tokens'] += u['output_tokens']
            row['cost_usd'] += u['cost_usd']
            row['model'] = u['model']
    with open(OUT_DIR / 'token_usage_summary.csv', 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['stage','model','runs','avg_input_tokens','avg_output_tokens','avg_cost_usd'])
        writer.writeheader()
        for stage,row in stage_rows.items():
            writer.writerow({
                'stage': stage,
                'model': row['model'],
                'runs': row['runs'],
                'avg_input_tokens': round(row['input_tokens']/row['runs'], 1),
                'avg_output_tokens': round(row['output_tokens']/row['runs'], 1),
                'avg_cost_usd': round(row['cost_usd']/row['runs'], 8)
            })
    avg_run_cost = sum(r['measured_total_cost_usd'] for r in results) / len(results)
    summary = {'representative_runs': len(results), 'average_cost_per_run_usd': round(avg_run_cost, 8), 'total_cost_all_runs_usd': round(sum(r['measured_total_cost_usd'] for r in results), 8)}
    (OUT_DIR / 'run_summary.json').write_text(json.dumps(summary, indent=2))


if __name__ == '__main__':
    results = []
    for run_id in ['base','renewal_risk','support_spike','quality_batch','segment_decline']:
        results.append(run_workflow(run_id))
    write_summaries(results)
    print(json.dumps({'status':'ok','runs':len(results),'outputs_dir':str(OUT_DIR)}, indent=2))
