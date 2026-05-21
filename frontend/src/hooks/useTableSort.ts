import { useState, useMemo } from 'react';

interface SortState {
  index?: number;
  direction?: 'asc' | 'desc';
}

export function useTableSort<T>(
  data: T[],
  columns: { key: string; getter: (item: T) => string | number | null | undefined }[],
  defaultSort?: SortState,
) {
  const [sortBy, setSortBy] = useState<SortState>(defaultSort ?? {});

  const onSort = (_event: unknown, index: number, direction: 'asc' | 'desc') => {
    setSortBy({ index, direction });
  };

  const sorted = useMemo(() => {
    if (sortBy.index == null || sortBy.direction == null) return data;
    const col = columns[sortBy.index];
    if (!col) return data;

    return [...data].sort((a, b) => {
      const av = col.getter(a);
      const bv = col.getter(b);
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      const cmp = typeof av === 'string' && typeof bv === 'string'
        ? av.localeCompare(bv)
        : Number(av) - Number(bv);
      return sortBy.direction === 'desc' ? -cmp : cmp;
    });
  }, [data, columns, sortBy]);

  const getSortParams = (index: number) => ({
    sort: {
      sortBy,
      onSort,
      columnIndex: index,
    },
  });

  return { sorted, getSortParams };
}
