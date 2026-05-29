import { useParams } from 'react-router-dom';

export default function ClusterDetail() {
  const { name } = useParams<{ name: string }>();
  return (
    <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8">
      <h1 className="text-3xl font-bold text-white mb-2" style={{ fontFamily: 'Red Hat Display' }}>Cluster Detail</h1>
      <p className="text-[#6A6E73]">Cluster: {name}</p>
    </div>
  )
}
