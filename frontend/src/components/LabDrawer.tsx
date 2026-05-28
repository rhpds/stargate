import {
  DescriptionList,
  DescriptionListDescription,
  DescriptionListGroup,
  DescriptionListTerm,
  Label,
  Spinner,
} from '@patternfly/react-core';
import { Table, Thead, Tr, Th, Tbody, Td } from '@patternfly/react-table';
import { useLabDetail } from '../api/hooks';
import type { Deployment, PoolEntry } from '../api/types';
import StatusLabel from './StatusLabel';
import AIAnalysis from './AIAnalysis';
import FeedbackForm from './FeedbackForm';
import StagePipeline from './StagePipeline';
import ClassificationBadge from './ClassificationBadge';
import { api } from '../api/client';
import type { PipelineStage } from '../api/types';

interface Props {
  lab: Deployment;
  pool: PoolEntry | null;
}

export default function LabDrawer({ lab, pool }: Props) {
  const { data, isLoading } = useLabDetail(lab.lab_code);

  return (
    <div style={{ padding: '0.5rem' }}>
      {/* Provisioning Status */}
      <h4 style={{ marginBottom: '0.5rem' }}>Provisioning</h4>
      <DescriptionList isHorizontal isCompact>
        <DescriptionListGroup>
          <DescriptionListTerm>Stage</DescriptionListTerm>
          <DescriptionListDescription>
            {lab.labagator_status === 'in_development'
              ? <Label isCompact color="green">Building</Label>
              : <Label isCompact color="blue">Planning</Label>
            }
          </DescriptionListDescription>
        </DescriptionListGroup>
        <DescriptionListGroup>
          <DescriptionListTerm>Cloud</DescriptionListTerm>
          <DescriptionListDescription>{lab.cloud || 'Not assigned'}</DescriptionListDescription>
        </DescriptionListGroup>
        <DescriptionListGroup>
          <DescriptionListTerm>Deploy Mode</DescriptionListTerm>
          <DescriptionListDescription>{lab.deploy_mode || '-'}</DescriptionListDescription>
        </DescriptionListGroup>
        <DescriptionListGroup>
          <DescriptionListTerm>Provisioned</DescriptionListTerm>
          <DescriptionListDescription>
            {lab.instances_total > 0 ? (
              <span>
                <strong style={{ color: lab.instances_started === lab.instances_total ? 'var(--sg-color--healthy)' : lab.instances_started > 0 ? 'var(--sg-color--warning)' : 'var(--sg-color--critical)' }}>
                  {lab.instances_started}
                </strong> / {lab.instances_total} instances up
              </span>
            ) : lab.provisioned > 0 || lab.capacity > 0 ? (
              <span>
                <strong style={{ color: lab.provisioned >= lab.capacity && lab.capacity > 0 ? 'var(--sg-color--healthy)' : 'var(--sg-color--warning)' }}>
                  {lab.provisioned}
                </strong> / {lab.capacity} pools ready
              </span>
            ) : (
              <span style={{ color: 'var(--sg-color--warning)' }}>No pools allocated</span>
            )}
          </DescriptionListDescription>
        </DescriptionListGroup>
        {lab.agnosticv_tags.length > 0 && (
          <DescriptionListGroup>
            <DescriptionListTerm>Tags</DescriptionListTerm>
            <DescriptionListDescription>
              {lab.agnosticv_tags.map(t => <Label key={t} isCompact color="blue" style={{ marginRight: '3px', marginBottom: '2px' }}>{t}</Label>)}
            </DescriptionListDescription>
          </DescriptionListGroup>
        )}
        {lab.agnosticv_timeout != null && (
          <DescriptionListGroup>
            <DescriptionListTerm>Timeout</DescriptionListTerm>
            <DescriptionListDescription>
              {lab.agnosticv_timeout >= 3600
                ? `${Math.round(lab.agnosticv_timeout / 3600)}h`
                : `${Math.round(lab.agnosticv_timeout / 60)}m`}
              {lab.agnosticv_timeout <= 3600 && <span style={{ color: 'var(--sg-color--healthy)', marginLeft: '0.5rem', fontSize: '0.85rem' }}>quick cleanup</span>}
              {lab.agnosticv_timeout > 18000 && <span style={{ color: 'var(--sg-color--warning)', marginLeft: '0.5rem', fontSize: '0.85rem' }}>long-running</span>}
            </DescriptionListDescription>
          </DescriptionListGroup>
        )}
        {lab.agnosticv_config && (
          <DescriptionListGroup>
            <DescriptionListTerm>Config Type</DescriptionListTerm>
            <DescriptionListDescription>
              <Label isCompact color={lab.agnosticv_config === 'namespace' ? 'green' : lab.agnosticv_config === 'openshift-cluster' ? 'red' : 'blue'}>
                {lab.agnosticv_config}
              </Label>
            </DescriptionListDescription>
          </DescriptionListGroup>
        )}
        {lab.instances_failed > 0 && (
          <DescriptionListGroup>
            <DescriptionListTerm>Stuck Instances</DescriptionListTerm>
            <DescriptionListDescription>
              <strong style={{ color: 'var(--sg-color--critical)' }}>{lab.instances_failed}</strong>
              <span style={{ color: 'var(--rh-color--text-secondary, #6a6e73)', marginLeft: '0.5rem', fontSize: '0.85rem' }}>
                (destroy-failed or provision-error — consuming resources)
              </span>
            </DescriptionListDescription>
          </DescriptionListGroup>
        )}
        {lab.instances_destroying > 0 && (
          <DescriptionListGroup>
            <DescriptionListTerm>Destroying</DescriptionListTerm>
            <DescriptionListDescription>
              <strong style={{ color: 'var(--sg-color--warning)' }}>{lab.instances_destroying}</strong> being cleaned up
            </DescriptionListDescription>
          </DescriptionListGroup>
        )}
        {lab.schedule_dates.length > 0 && (
          <DescriptionListGroup>
            <DescriptionListTerm>Schedule</DescriptionListTerm>
            <DescriptionListDescription>
              {lab.schedule_dates.map(d => <Label key={d} isCompact color="blue" style={{ marginRight: '4px' }}>{d}</Label>)}
            </DescriptionListDescription>
          </DescriptionListGroup>
        )}
        {lab.demolition_status !== 'none' && (
          <DescriptionListGroup>
            <DescriptionListTerm>Health Check</DescriptionListTerm>
            <DescriptionListDescription>
              {lab.demolition_status === 'pass'
                ? <Label isCompact color="green">Pass ({lab.demolition_completed}/{lab.demolition_total})</Label>
                : <Label isCompact color="red">Fail ({lab.demolition_failed}/{lab.demolition_total} failed)</Label>}
            </DescriptionListDescription>
          </DescriptionListGroup>
        )}
        <DescriptionListGroup>
          <DescriptionListTerm>Sessions</DescriptionListTerm>
          <DescriptionListDescription>
            {lab.sessions > 0
              ? <strong>{lab.sessions}</strong>
              : <span style={{ color: 'var(--rh-color--text-secondary)' }}>Not scheduled</span>
            }
          </DescriptionListDescription>
        </DescriptionListGroup>
      </DescriptionList>

      {/* Readiness Progress */}
      <h4 style={{ marginTop: '1rem', marginBottom: '0.5rem' }}>Readiness Checklist</h4>
      <div style={{ fontSize: '0.9rem' }}>
        <CheckItem label="Content development" done={lab.labagator_status === 'in_development'} detail={lab.labagator_status === 'in_development' ? 'Active' : 'Still planning'} />
        <CheckItem label="Sessions scheduled" done={lab.sessions > 0} detail={lab.sessions > 0 ? `${lab.sessions} session(s)` : 'None yet'} />
        <CheckItem label="Provisioned" done={lab.instances_started > 0 || lab.provisioned > 0} detail={lab.instances_started > 0 ? `${lab.instances_started}/${lab.instances_total} instances up` : lab.provisioned > 0 ? `${lab.provisioned}/${lab.capacity} pools` : 'No provisioning'} />
        <CheckItem label="Smoke test" done={lab.demolition_status === 'pass'} detail={lab.demolition_status === 'pass' ? `Passing (${lab.demolition_completed}/${lab.demolition_total})` : lab.demolition_status === 'fail' ? `Failing (${lab.demolition_failed}/${lab.demolition_total} failed)` : 'Not tested'} />
      </div>

      {/* CI Name */}
      {lab.ci_name && (
        <>
          <h4 style={{ marginTop: '1rem', marginBottom: '0.5rem' }}>Catalog Item</h4>
          <div style={{ fontSize: '0.85rem', wordBreak: 'break-all', color: 'var(--rh-color--text-secondary)' }}>{lab.ci_name}</div>
        </>
      )}

      {/* Pool health if available */}
      {pool && (
        <>
          <h4 style={{ marginTop: '1rem', marginBottom: '0.5rem' }}>Sandbox Pool: {pool.pool}</h4>
          <DescriptionList isHorizontal isCompact>
            <DescriptionListGroup>
              <DescriptionListTerm>Health</DescriptionListTerm>
              <DescriptionListDescription><strong style={{ color: (pool.health ?? 0) >= 80 ? 'var(--sg-color--healthy)' : 'var(--sg-color--warning)' }}>{pool.health?.toFixed(1)}%</strong></DescriptionListDescription>
            </DescriptionListGroup>
            <DescriptionListGroup>
              <DescriptionListTerm>Instances</DescriptionListTerm>
              <DescriptionListDescription>{pool.instances} across {pool.clusters.join(', ')}</DescriptionListDescription>
            </DescriptionListGroup>
            <DescriptionListGroup>
              <DescriptionListTerm>Evaluations</DescriptionListTerm>
              <DescriptionListDescription>{pool.passed} passed / {pool.failed} failed / {pool.warned} warned</DescriptionListDescription>
            </DescriptionListGroup>
            {pool.top_failure_class && (
              <DescriptionListGroup>
                <DescriptionListTerm>Top Failure</DescriptionListTerm>
                <DescriptionListDescription><Label isCompact color="red">{pool.top_failure_class}</Label></DescriptionListDescription>
              </DescriptionListGroup>
            )}
          </DescriptionList>
        </>
      )}

      {/* Labagator detail from API */}
      {isLoading && <Spinner size="md" style={{ marginTop: '1rem' }} />}

      {data?.labagator && (
        <>
          <h4 style={{ marginTop: '1rem', marginBottom: '0.5rem' }}>People</h4>
          <DescriptionList isHorizontal isCompact>
            {data.labagator.lead_developer && <DescriptionListGroup><DescriptionListTerm>Lead</DescriptionListTerm><DescriptionListDescription>{data.labagator.lead_developer}</DescriptionListDescription></DescriptionListGroup>}
            {data.labagator.rhdp_developer && <DescriptionListGroup><DescriptionListTerm>RHDP</DescriptionListTerm><DescriptionListDescription>{data.labagator.rhdp_developer}</DescriptionListDescription></DescriptionListGroup>}
            {data.labagator.ops_assigned && <DescriptionListGroup><DescriptionListTerm>Ops</DescriptionListTerm><DescriptionListDescription>{data.labagator.ops_assigned}</DescriptionListDescription></DescriptionListGroup>}
          </DescriptionList>
        </>
      )}

      {data?.labagator_sessions && data.labagator_sessions.length > 0 && (
        <>
          <h4 style={{ marginTop: '1rem', marginBottom: '0.5rem' }}>Sessions</h4>
          <Table aria-label="Sessions" variant="compact">
            <Thead><Tr><Th>Date</Th><Th>Time</Th><Th>Room</Th><Th>Seats</Th></Tr></Thead>
            <Tbody>
              {data.labagator_sessions.map((s, i) => (
                <Tr key={i}><Td>{s.session_date}</Td><Td>{s.start_time}</Td><Td>{s.room}</Td><Td>{s.attendees}</Td></Tr>
              ))}
            </Tbody>
          </Table>
        </>
      )}

      {data?.stargate.history && data.stargate.history.length > 0 && (() => {
        const stageMap: Record<string, PipelineStage> = {};
        for (const ev of data.stargate.history) {
          if (!stageMap[ev.stage_id]) stageMap[ev.stage_id] = { stage_id: ev.stage_id, order: 0, pass: 0, fail: 0, warn: 0, total: 0, health_rate: null };
          const s = stageMap[ev.stage_id]!;
          s.total++;
          if (ev.outcome === 'pass') s.pass++;
          else if (ev.outcome === 'fail') s.fail++;
          else if (ev.outcome === 'warn') s.warn++;
        }
        const pipelineStages = Object.values(stageMap);
        pipelineStages.forEach(s => { s.health_rate = s.total > 0 ? Math.round((s.pass + s.warn) / s.total * 100) : null; });
        return pipelineStages.length > 0 ? (
          <>
            <h4 style={{ marginTop: '1rem', marginBottom: '0.5rem' }}>Stage Pipeline</h4>
            <StagePipeline stages={pipelineStages} compact />
          </>
        ) : null;
      })()}

      {data?.stargate.history && data.stargate.history.length > 0 && (
        <>
          <h4 style={{ marginTop: '1rem', marginBottom: '0.5rem' }}>Recent Evaluations</h4>
          <Table aria-label="Evaluations" variant="compact">
            <Thead><Tr><Th>Time</Th><Th>Outcome</Th><Th>Failure</Th><Th>AI Classification</Th></Tr></Thead>
            <Tbody>
              {data.stargate.history.slice(0, 10).map((e, i) => {
                const proposal = (data.stargate as any).proposed_classifications?.find(
                  (p: any) => p.run_id === e.run_id && p.stage_id === e.stage_id
                );
                return (
                  <Tr key={i}>
                    <Td style={{ fontSize: '0.8rem' }}>{e.evaluated_at ? new Date(e.evaluated_at).toLocaleString() : '-'}</Td>
                    <Td><StatusLabel status={e.outcome} isCompact /></Td>
                    <Td style={{ fontSize: '0.85rem' }}>{e.failure_class || '-'}</Td>
                    <Td>
                      {proposal ? (
                        <ClassificationBadge
                          proposedClass={proposal.proposed_class}
                          confidence={proposal.confidence}
                          reviewed={proposal.reviewed}
                          approved={proposal.approved}
                          proposalId={proposal.id}
                          onApprove={(id) => api.reviewClassification(id, true)}
                          onReject={(id) => api.reviewClassification(id, false)}
                        />
                      ) : e.outcome === 'fail' ? (
                        <span style={{ fontSize: '0.75rem', color: 'var(--rh-color--text-secondary, #6a6e73)' }}>Pending...</span>
                      ) : '-'}
                    </Td>
                  </Tr>
                );
              })}
            </Tbody>
          </Table>
        </>
      )}

      {(data as any)?.constraint_violations?.length > 0 && (
        <>
          <h4 style={{ marginTop: '1rem', marginBottom: '0.5rem' }}>Constraint Violations</h4>
          <Table aria-label="Constraint violations" variant="compact">
            <Thead><Tr><Th>Type</Th><Th>Expected</Th><Th>Actual</Th><Th>Severity</Th></Tr></Thead>
            <Tbody>
              {(data as any).constraint_violations.map((v: any, i: number) => (
                <Tr key={i}>
                  <Td style={{ fontWeight: 600, fontSize: '0.85rem' }}>{v.type}</Td>
                  <Td style={{ fontSize: '0.85rem' }}>{v.expected || '-'}</Td>
                  <Td style={{ fontSize: '0.85rem', color: 'var(--sg-color--critical)' }}>{v.actual || '-'}</Td>
                  <Td><Label isCompact color={v.severity === 'error' ? 'red' : 'orange'}>{v.severity}</Label></Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        </>
      )}

      {data?.demolition && data.demolition.length > 0 && (() => {
        const sorted = [...data.demolition].sort((a, b) => (b.id as number) - (a.id as number));
        const realTests = sorted.filter(d => d.total > 5);
        const latest = realTests[0] ?? sorted[0];
        const failRate = latest && latest.total > 0 ? Math.round(latest.failed / latest.total * 100) : 0;
        const failureClasses = data.stargate.failure_classes;
        const topFailures = Object.entries(failureClasses).sort(([,a],[,b]) => (b as number) - (a as number)).slice(0, 5);

        return (
          <>
            <h4 style={{ marginTop: '1rem', marginBottom: '0.5rem' }}>Health Checks (Verification)</h4>

            {latest && (
              <div style={{ padding: '0.75rem', background: latest.failed > 0 ? 'var(--sg-color--critical-bg)' : 'var(--sg-color--healthy-bg)', borderRadius: '4px', marginBottom: '0.75rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                  <strong>Latest Load Test</strong>
                  <StatusLabel status={latest.failed > 0 ? 'failed' : 'passed'} isCompact />
                </div>
                <div style={{ fontSize: '0.9rem' }}>
                  <span><strong>{latest.completed}</strong> passed, <strong style={{ color: latest.failed > 0 ? 'var(--sg-color--critical)' : undefined }}>{latest.failed}</strong> failed of <strong>{latest.total}</strong> workers</span>
                  {latest.total > 0 && <span style={{ marginLeft: '0.5rem', color: 'var(--rh-color--text-secondary, #6a6e73)' }}>({failRate}% failure rate)</span>}
                </div>
                <div style={{ fontSize: '0.8rem', color: 'var(--rh-color--text-secondary, #6a6e73)', marginTop: '0.25rem' }}>{latest.name}</div>
              </div>
            )}

            {latest && latest.failed > 0 && (
              <div style={{ marginBottom: '0.75rem' }}>
                <h4 style={{ marginBottom: '0.25rem', fontSize: '0.9rem' }}>Likely Failure Causes</h4>
                {topFailures.length > 0 ? (
                  <div style={{ fontSize: '0.85rem' }}>
                    {topFailures.map(([fc, count]) => (
                      <div key={fc} style={{ display: 'flex', justifyContent: 'space-between', padding: '0.15rem 0' }}>
                        <Label isCompact color="red">{fc}</Label>
                        <span>{count as number} occurrences</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div style={{ fontSize: '0.85rem', color: 'var(--rh-color--text-secondary, #6a6e73)' }}>
                    No StarGate evaluations available for this lab yet. The smoke test failures may be caused by:
                    <ul style={{ margin: '0.25rem 0', paddingLeft: '1.2rem' }}>
                      <li>Provisioning not complete — instances not fully started</li>
                      <li>Route/service not ready — application not responding</li>
                      <li>Showroom content not loaded — workshop UI not accessible</li>
                    </ul>
                    Use the AI analysis below for specific diagnostics.
                  </div>
                )}
              </div>
            )}

            {sorted.length > 1 && (
              <>
                <h4 style={{ marginBottom: '0.25rem', fontSize: '0.9rem' }}>Test History ({sorted.length} runs)</h4>
                <Table aria-label="Verification history" variant="compact">
                  <Thead><Tr><Th>Run</Th><Th>Status</Th><Th>Passed</Th><Th>Failed</Th><Th>Total</Th><Th>Rate</Th></Tr></Thead>
                  <Tbody>
                    {sorted.slice(0, 5).map(d => (
                      <Tr key={d.id}>
                        <Td style={{ fontSize: '0.8rem', maxWidth: '150px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{d.name}</Td>
                        <Td><StatusLabel status={d.status} isCompact /></Td>
                        <Td style={{ color: 'var(--sg-color--healthy)' }}>{d.completed}</Td>
                        <Td style={{ color: d.failed > 0 ? 'var(--sg-color--critical)' : undefined }}>{d.failed}</Td>
                        <Td>{d.total}</Td>
                        <Td>{d.total > 0 ? `${Math.round((d.total - d.failed) / d.total * 100)}%` : '-'}</Td>
                      </Tr>
                    ))}
                  </Tbody>
                </Table>
              </>
            )}
          </>
        );
      })()}

      {data?.constraints && (
        <>
          <h4 style={{ marginTop: '1rem', marginBottom: '0.5rem' }}>Constraints</h4>
          <DescriptionList isHorizontal isCompact>
            {data.constraints.cloud_provider != null && (
              <DescriptionListGroup>
                <DescriptionListTerm>Cloud</DescriptionListTerm>
                <DescriptionListDescription>{String(data.constraints.cloud_provider)}</DescriptionListDescription>
              </DescriptionListGroup>
            )}
            {data.constraints.ocp_version != null && (
              <DescriptionListGroup>
                <DescriptionListTerm>OCP Version</DescriptionListTerm>
                <DescriptionListDescription>{String(data.constraints.ocp_version)}</DescriptionListDescription>
              </DescriptionListGroup>
            )}
            {Array.isArray(data.constraints.workloads) && (
              <DescriptionListGroup>
                <DescriptionListTerm>Workloads</DescriptionListTerm>
                <DescriptionListDescription>
                  {(data.constraints.workloads as string[]).map(w => (
                    <Label key={w} isCompact style={{ marginRight: '4px', marginBottom: '2px' }}>{w}</Label>
                  ))}
                </DescriptionListDescription>
              </DescriptionListGroup>
            )}
          </DescriptionList>
        </>
      )}

      <AIAnalysis contextType="lab" labCode={lab.lab_code} />

      {data?.stargate.history?.[0]?.run_id && data.stargate.history[0].outcome === 'fail' && (
        <FeedbackForm
          runId={data.stargate.history[0].run_id}
          currentClass={data.stargate.history[0].failure_class ?? null}
        />
      )}
    </div>
  );
}

function CheckItem({ label, done, detail }: { label: string; done: boolean; detail: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', padding: '0.25rem 0' }}>
      <span style={{ color: done ? 'var(--sg-color--healthy)' : 'var(--rh-color--text-secondary)', fontSize: '1.1rem' }}>
        {done ? '✓' : '✗'}
      </span>
      <span>{label}</span>
      <span style={{ fontSize: '0.85rem', color: 'var(--rh-color--text-secondary)', marginLeft: 'auto' }}>{detail}</span>
    </div>
  );
}
