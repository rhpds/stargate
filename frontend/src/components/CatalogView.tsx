import { useState, useMemo } from 'react';
import {
  Card, CardBody, CardTitle, Gallery, GalleryItem,
  Label, SearchInput, Spinner, Toolbar, ToolbarContent, ToolbarItem,
  Select, SelectOption, MenuToggle,
} from '@patternfly/react-core';
import { Table, Thead, Tr, Th, Tbody, Td } from '@patternfly/react-table';
import { useCatalog } from '../api/hooks';
import type { CatalogItem } from '../api/types';

export default function CatalogView() {
  const { data, isLoading } = useCatalog();
  const [search, setSearch] = useState('');
  const [sourceFilter, setSourceFilter] = useState('');
  const [sourceOpen, setSourceOpen] = useState(false);
  const [categoryFilter, setCategoryFilter] = useState('');
  const [categoryOpen, setCategoryOpen] = useState(false);
  const [showDisabled, setShowDisabled] = useState(false);

  const filtered = useMemo(() => {
    if (!data) return [];
    return data.items.filter(item => {
      if (!showDisabled && item.disabled) return false;
      if (sourceFilter && item.source !== sourceFilter) return false;
      if (categoryFilter && item.category !== categoryFilter) return false;
      if (search) {
        const q = search.toLowerCase();
        return item.name.toLowerCase().includes(q)
          || item.display_name.toLowerCase().includes(q)
          || (item.lab_code || '').toLowerCase().includes(q)
          || item.description.toLowerCase().includes(q);
      }
      return true;
    });
  }, [data, search, sourceFilter, categoryFilter, showDisabled]);

  if (isLoading) return <Spinner size="lg" />;
  if (!data) return <em>No catalog data available. Babylon worker may not have collected CatalogItems yet.</em>;

  const categories = Object.keys(data.by_category).sort();

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
      <Gallery hasGutter minWidths={{ default: '140px' }}>
        <GalleryItem>
          <Card isCompact isFullHeight>
            <CardTitle style={{ fontSize: '0.85rem' }}>Total Items</CardTitle>
            <CardBody style={{ paddingTop: 0 }}>
              <span style={{ fontSize: '1.5rem', fontWeight: 700 }}>{data.total}</span>
            </CardBody>
          </Card>
        </GalleryItem>
        <GalleryItem>
          <Card isCompact isFullHeight>
            <CardTitle style={{ fontSize: '0.85rem' }}>Active</CardTitle>
            <CardBody style={{ paddingTop: 0 }}>
              <span style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--sg-color--healthy)' }}>{data.active}</span>
            </CardBody>
          </Card>
        </GalleryItem>
        <GalleryItem>
          <Card isCompact isFullHeight>
            <CardTitle style={{ fontSize: '0.85rem' }}>Disabled</CardTitle>
            <CardBody style={{ paddingTop: 0 }}>
              <span style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--rh-color--text-secondary)' }}>{data.disabled}</span>
            </CardBody>
          </Card>
        </GalleryItem>
        {categories.map(cat => (
          <GalleryItem key={cat}>
            <Card isCompact isFullHeight>
              <CardTitle style={{ fontSize: '0.85rem' }}>{cat}</CardTitle>
              <CardBody style={{ paddingTop: 0 }}>
                <span style={{ fontSize: '1.5rem', fontWeight: 700 }}>{data.by_category[cat]}</span>
              </CardBody>
            </Card>
          </GalleryItem>
        ))}
      </Gallery>

      <Card>
        <CardTitle>Platform Catalog — All Deployable Items</CardTitle>
        <CardBody>
          <Toolbar>
            <ToolbarContent>
              <ToolbarItem>
                <SearchInput placeholder="Search catalog..." value={search} onChange={(_e, v) => setSearch(v)} onClear={() => setSearch('')} style={{ minWidth: '250px' }} />
              </ToolbarItem>
              <ToolbarItem>
                <Select
                  toggle={(ref) => <MenuToggle ref={ref} onClick={() => setSourceOpen(!sourceOpen)} isExpanded={sourceOpen}>{sourceFilter || 'All sources'}</MenuToggle>}
                  isOpen={sourceOpen}
                  onSelect={(_e, v) => { setSourceFilter(v as string); setSourceOpen(false); }}
                  onOpenChange={setSourceOpen}
                  selected={sourceFilter}
                >
                  <SelectOption value="">All sources</SelectOption>
                  <SelectOption value="babylon">Babylon</SelectOption>
                  <SelectOption value="zerotouch">ZeroTouch</SelectOption>
                </Select>
              </ToolbarItem>
              <ToolbarItem>
                <Select
                  toggle={(ref) => <MenuToggle ref={ref} onClick={() => setCategoryOpen(!categoryOpen)} isExpanded={categoryOpen}>{categoryFilter || 'All categories'}</MenuToggle>}
                  isOpen={categoryOpen}
                  onSelect={(_e, v) => { setCategoryFilter(v as string); setCategoryOpen(false); }}
                  onOpenChange={setCategoryOpen}
                  selected={categoryFilter}
                >
                  <SelectOption value="">All categories</SelectOption>
                  {categories.map(c => <SelectOption key={c} value={c}>{c}</SelectOption>)}
                </Select>
              </ToolbarItem>
              <ToolbarItem>
                <Label isCompact color={showDisabled ? 'blue' : 'grey'} onClick={() => setShowDisabled(!showDisabled)} style={{ cursor: 'pointer' }}>
                  {showDisabled ? 'Showing disabled' : 'Hiding disabled'}
                </Label>
              </ToolbarItem>
            </ToolbarContent>
          </Toolbar>

          <div style={{ fontSize: '0.85rem', marginBottom: '0.5rem', color: 'var(--rh-color--text-secondary)' }}>
            {filtered.length} items | Sources: {data.sources.map(s => <Label key={s} isCompact color="blue" style={{ marginRight: '4px' }}>{s}</Label>)}
          </div>

          <Table aria-label="Platform catalog" variant="compact">
            <Thead>
              <Tr>
                <Th>Name</Th>
                <Th>Source</Th>
                <Th>Category</Th>
                <Th>Lab Code</Th>
                <Th>Status</Th>
                <Th>Provider</Th>
                <Th>Complexity</Th>
              </Tr>
            </Thead>
            <Tbody>
              {filtered.slice(0, 100).map((item: CatalogItem) => (
                <Tr key={`${item.source}-${item.name}`}>
                  <Td>
                    <div>
                      <strong>{item.display_name || item.name}</strong>
                      {item.description && <div style={{ fontSize: '0.75rem', color: 'var(--rh-color--text-secondary)', maxWidth: '300px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.description}</div>}
                    </div>
                  </Td>
                  <Td><Label isCompact color={item.source === 'babylon' ? 'blue' : item.source === 'zerotouch' ? 'orange' : 'grey'}>{item.source}</Label></Td>
                  <Td>{item.category}</Td>
                  <Td>{item.lab_code ? <Label isCompact color="purple">{item.lab_code}</Label> : <span style={{ color: 'var(--rh-color--text-secondary)' }}>—</span>}</Td>
                  <Td>{item.disabled ? <Label isCompact color="grey">Disabled</Label> : <Label isCompact color="green">Active</Label>}</Td>
                  <Td style={{ fontSize: '0.8rem' }}>{item.provider || '—'}</Td>
                  <Td>
                    {item.complexity ? (
                      <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                        <div style={{ width: '40px', height: '6px', background: '#f0f0f0', borderRadius: '3px', overflow: 'hidden' }}>
                          <div style={{ width: `${item.complexity.score * 100}%`, height: '100%', background: item.complexity.score > 0.7 ? '#c9190b' : item.complexity.score > 0.4 ? '#f0ab00' : '#3e8635' }} />
                        </div>
                        <span style={{ fontSize: '0.75rem' }}>{item.complexity.score.toFixed(2)}</span>
                      </div>
                    ) : <span style={{ color: 'var(--rh-color--text-secondary)' }}>—</span>}
                  </Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
          {filtered.length > 100 && <div style={{ padding: '0.5rem', color: 'var(--rh-color--text-secondary)' }}>Showing first 100 of {filtered.length} items</div>}
        </CardBody>
      </Card>
    </div>
  );
}
