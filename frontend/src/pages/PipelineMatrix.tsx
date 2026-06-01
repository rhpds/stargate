import { useNavigate } from 'react-router-dom';
import { useEvaluationMatrix } from '../api/hooks';
import type { EvaluationMatrix } from '../api/types';

/* ---- helpers ---- */

const OUTCOME_COLORS: Record<string, string> = {
  pass: '#3E8635',
  fail: '#C9190B',
  warn: '#F0AB00',
};

function cellColor(outcome: string | undefined): string {
  if (!outcome) return '#2e2e2e'; // gray — not evaluated
  return OUTCOME_COLORS[outcome.toLowerCase()] ?? '#2e2e2e';
}

function cellLabel(outcome: string | undefined): string {
  if (!outcome) return '--';
  return outcome;
}

/* ---- main page ---- */

export default function PipelineMatrix() {
  const navigate = useNavigate();
  const matrixQuery = useEvaluationMatrix();

  if (matrixQuery.isLoading) {
    return (
      <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8">
        <p className="text-[#6A6E73]">Loading...</p>
      </div>
    );
  }

  if (matrixQuery.isError) {
    return (
      <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8">
        <p className="text-[#C9190B]">Failed to load pipeline matrix.</p>
      </div>
    );
  }

  const data = matrixQuery.data as EvaluationMatrix;
  const { labs, stages, matrix } = data;
  const ecosystemLabs = new Set((data as any).ecosystem_labs ?? []);
  const labClusters: Record<string, string> = (data as any).lab_clusters ?? {};

  if (labs.length === 0 || stages.length === 0) {
    return (
      <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8 space-y-6">
        <div>
          <h1 className="text-3xl font-bold text-white mb-2" style={{ fontFamily: 'Red Hat Display' }}>
            Pipeline Matrix
          </h1>
          <p className="text-[#6A6E73]">Lab x Stage evaluation outcomes</p>
        </div>
        <p className="text-[#6A6E73] text-sm">No evaluation data available.</p>
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-white mb-2" style={{ fontFamily: 'Red Hat Display' }}>
          Pipeline Matrix
        </h1>
        <p className="text-[#6A6E73]">Lab x Stage evaluation outcomes</p>
      </div>

      {/* Matrix grid */}
      <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4 overflow-x-auto">
        <table className="w-full border-collapse">
          <thead>
            <tr>
              <th className="text-left text-xs text-[#6A6E73] uppercase tracking-wider font-bold p-2 sticky left-0 bg-[#212121] z-10 min-w-[160px]">
                Lab
              </th>
              <th className="text-left text-xs text-[#6A6E73] uppercase tracking-wider font-bold p-2 min-w-[100px]">
                Cluster
              </th>
              {stages.map((stage) => (
                <th
                  key={stage}
                  className="text-center text-xs text-[#6A6E73] uppercase tracking-wider font-bold p-2 min-w-[80px]"
                >
                  <span className="block truncate max-w-[100px]" title={stage}>
                    {stage}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {labs.map((lab) => {
              const labRow = matrix[lab] ?? {};
              const isEco = ecosystemLabs.has(lab);
              return (
                <tr
                  key={lab}
                  className={`hover:bg-[#2a2a2a] cursor-pointer transition ${isEco ? 'border-l-2 border-l-[#EE0000]' : 'opacity-60'}`}
                  onClick={() => navigate(`/lab/${lab}`)}
                >
                  <td className="text-sm p-2 truncate sticky left-0 bg-[#212121] z-10 max-w-[200px]" title={lab}>
                    <span className={isEco ? 'text-white font-medium' : 'text-[#8A8D90]'}>{lab}</span>
                    {isEco && <span className="ml-1.5 text-[10px] text-[#EE0000] font-bold uppercase">eco</span>}
                  </td>
                  <td className="text-xs text-[#8A8D90] p-2 truncate" title={labClusters[lab] || ''}>
                    {labClusters[lab] || '--'}
                  </td>
                  {stages.map((stage) => {
                    const outcome = labRow[stage];
                    return (
                      <td key={stage} className="p-1.5 text-center">
                        <div
                          className="rounded h-8 flex items-center justify-center text-[10px] font-semibold text-white uppercase"
                          style={{ backgroundColor: cellColor(outcome) }}
                          title={`${lab} / ${stage}: ${cellLabel(outcome)}`}
                        >
                          {cellLabel(outcome)}
                        </div>
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Legend */}
      <div className="flex items-center gap-4 text-xs text-[#6A6E73]">
        <span className="uppercase tracking-wider font-bold">Legend:</span>
        <div className="flex items-center gap-1.5">
          <div className="w-3 h-3 rounded" style={{ backgroundColor: '#3E8635' }} />
          <span>Pass</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-3 h-3 rounded" style={{ backgroundColor: '#C9190B' }} />
          <span>Fail</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-3 h-3 rounded" style={{ backgroundColor: '#F0AB00' }} />
          <span>Warn</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-3 h-3 rounded" style={{ backgroundColor: '#2e2e2e' }} />
          <span>Not evaluated</span>
        </div>
      </div>
    </div>
  );
}
