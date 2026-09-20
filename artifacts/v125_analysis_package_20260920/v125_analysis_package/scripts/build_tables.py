import os,json,gzip,orjson,glob,collections,hashlib,zipfile,io,math
import pandas as pd,numpy as np
D=os.environ.get('KAGGRI_OUTPUT_DIR',os.path.abspath('analysis_v125'));O=os.environ.get('KAGGRI_TABLES_DIR',os.path.join(D,'tables'));os.makedirs(O,exist_ok=True);m=pd.read_csv(D+'/enriched_episode_metrics.csv').fillna(0);c=pd.read_csv(D+'/observed_crop_cohorts.csv');e=pd.read_csv(D+'/retirement_tile_reuse.csv');P=['WHEAT','CARROT','TOMATO','STRAWBERRY','MELON','EGG','MILK','WOOL','FERTILIZER'];names={56357320:'v124_1',56360233:'v124_2',56216119:'Top1',56361903:'Top2',56354460:'Top3'};m['label']=m.target_submission.map(names);m['group']=m.target_submission.map({**names,56357320:'v124',56360233:'v124'})
def wilson(w,n,z=1.959963984540054):
 p=w/n;den=1+z*z/n;mid=(p+z*z/(2*n))/den;h=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den;return mid-h,mid+h
perf=[]
for sid,g in m.groupby('target_submission'):
 w=sum(g.result=='win');lo,hi=wilson(w,len(g));perf.append({'submission_id':sid,'label':names[sid],'n_public':len(g),'wins':w,'losses':sum(g.result=='loss'),'draws':sum(g.result=='draw'),'win_rate':w/len(g),'win_rate_wilson_low':lo,'win_rate_wilson_high':hi,'last_rating':g.sort_values('end_time').updated_rating.iloc[-1],'last_timestamp_utc':g.sort_values('end_time').end_time.iloc[-1],'mean_opponent_rating':g.opponent_rating.mean(),'mean_cash':g.own_reward.mean(),'median_cash':g.own_reward.median(),'mean_margin':g.margin.mean()})
pd.DataFrame(perf).to_csv(O+'/performance_summary.csv',index=False)
bands=[];v=m[m.group=='v124']
for label,lo,hi in [('under1500',0,1500),('1500_1599',1500,1600),('1600_1699',1600,1700),('1700plus',1700,float('inf')),('1500plus',1500,float('inf')),('1600plus',1600,float('inf')),('all',0,float('inf'))]:
 g=v[(v.opponent_rating>=lo)&(v.opponent_rating<hi)];w=sum(g.result=='win');low,high=wilson(w,len(g));bands.append({'opponent_band':label,'n':len(g),'wins':w,'losses':len(g)-w,'win_rate':w/len(g),'wilson_low':low,'wilson_high':high,'mean_margin':g.margin.mean()})
pd.DataFrame(bands).to_csv(O+'/v124_rating_bands.csv',index=False)
floor=[];fin=[]
for name,g in m[m.flows_reconciled].groupby('group'):
 for p in P:
  q=g['actual_SELL_'+p+'_qty'].sum();cash=g['actual_SELL_'+p+'_cash'].sum();fq=g.get('realized_'+p+'_floor_qty',pd.Series([0])).sum();floor.append({'group':name,'product':p,'n_cash_reconciled':len(g),'mean_units_sold':q/len(g),'mean_revenue':cash/len(g),'weighted_sale_price':cash/q if q else 0,'mean_floor_units':fq/len(g),'floor_unit_share':fq/q if q else 0})
 cols=[x for x in g.columns if x.startswith('actual_') and x.endswith('_cash')]
 for col in cols:fin.append({'group':name,'n':len(g),'cash_item':col[7:],'mean':g[col].mean()})
pd.DataFrame(floor).to_csv(O+'/price_floor_sales.csv',index=False);pd.DataFrame(fin).to_csv(O+'/cash_flow_breakdown.csv',index=False)
c['group']=c.sid.map({**names,56357320:'v124',56360233:'v124'});first=c.groupby(['group','episode_id','crop']).planted_day.min().reset_index();fst=first.groupby(['group','crop']).planted_day.agg(['count','median','min','max']).reset_index();fst.to_csv(O+'/crop_first_plant_day.csv',index=False)
beh=[]
for name,g in m.groupby('group'):
 z={'group':name,'n':len(g),'tomato_games':int(sum(g.max_TOMATO>0)),'four_quadrant_games':int(sum(g.land_719==4)),'effective_opening144_variants':g.effective_opening144_hash.nunique(),'overflow_units_mean':g.overflow_total.mean(),'overflow_games':int(sum(g.overflow_total>0)),'atomic_seed_cancelled_requests':g.atomic_seed_cancellations.sum(),'atomic_seed_games':int(sum(g.atomic_seed_cancellations>0)),'terminal_shed_mean':g.final_shed.mean(),'terminal_carry_mean':g.final_carry.mean()}
 for p in P[:5]:z['fertilize_'+p+'_mean']=g.get('verified_fertilized_'+p,pd.Series([0])).mean()
 for a in ['COW','SHEEP','GOOSE']:z['final_'+a+'_mean']=g[a+'_719'].mean();z['max_'+a+'_mean']=g['max_'+a].mean()
 sub=e[e.sid.isin(g.target_submission.unique())];z['animal_exit_games']=sub.episode_id.nunique();z['animal_exit_count']=len(sub);z['exited_tiles_reused_crop']=sub.next_crop.notna().sum();z['animal_reuse_games']=sub[sub.next_crop.notna()].episode_id.nunique();beh.append(z)
pd.DataFrame(beh).to_csv(O+'/behavior_summary.csv',index=False)
# Preserve exact net decomposition and focused own-data rows.
for src in ['v124_same_game_net_cash_decomposition.csv','v124_same_game_cash_decomposition.csv','retirement_tile_reuse.csv']:
 import shutil;shutil.copy(D+'/'+src,O+'/'+src)
v.to_csv(O+'/v124_episode_metrics.csv',index=False)
m.to_csv(O+'/all_public_episode_metrics.csv',index=False)
# Audit counts are per unique episode, not per target perspective.
kind=collections.Counter();err_eps=collections.Counter();trans=0;allerrs=[]
for p in glob.glob(D+'/audit/*.gz'):
 a=orjson.loads(gzip.open(p,'rb').read());trans+=a['transitions_audited'];kset=set()
 for er in a['errors']:kind[er['kind']]+=1;kset.add(er['kind']);allerrs.append({'episode_id':a['episode_id'],**er})
 err_eps.update(kset)
inputs=[];pairs=[]
for p in glob.glob(os.path.join(os.environ.get('KAGGRI_INPUT_DIR',os.getcwd()),'*.zip')):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for x in iter(lambda:f.read(2**20),b''):h.update(x)
 with zipfile.ZipFile(p) as z:
  en=next((n for n in z.namelist() if n.endswith('episodes.csv')),None);episodeids=pd.read_csv(io.BytesIO(z.read(en))).episode_id.tolist() if en else []
 inputs.append({'filename':os.path.basename(p),'bytes':os.path.getsize(p),'sha256':h.hexdigest(),'episodes_count':len(episodeids),'episodes_idset_sha256':hashlib.sha256(orjson.dumps(sorted(episodeids))).hexdigest(),'replay_members':sum('/replay' in n and n.endswith('.json') for n in z.namelist())})
summary={'unique_replays':1009,'unique_public_replays':1004,'target_perspectives':1023,'public_target_perspectives':1018,'validation_perspectives':5,'unique_transitions_audited':trans,'engine_module_versions':m.module_version.unique().tolist(),'audit_error_counts':dict(kind),'audit_error_episode_counts':dict(err_eps),'target_cash_ledger_mismatch_rows':m[m.ledger_residual!=0][['episode_id','target_submission','ledger_residual']].to_dict('records'),'v124_cash_ledger_mismatch_rows':int(sum(v.ledger_residual!=0)),'method':'One-transition independent audit resynchronized to each recorded prior observation, NOT a full closed-loop simulator or counterfactual win test. Shed ordering mismatches reconciled retrospectively by observed stock conservation; cash-comparison tables exclude the one target perspective with a 120 cash discrepancy.','inputs':inputs}
open(O+'/audit_and_provenance.json','w').write(json.dumps(summary,ensure_ascii=False,indent=2));open(O+'/audit_raw_mismatches.json','w').write(json.dumps(allerrs,ensure_ascii=False,indent=2));print(json.dumps(summary,ensure_ascii=False,indent=2));print(pd.DataFrame(beh).to_string(index=False));print(pd.DataFrame(bands).to_string(index=False))
