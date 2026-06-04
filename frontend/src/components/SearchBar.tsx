import { useState, useEffect } from 'react';

interface SearchBarProps {
  placeholder?: string;
  value: string;
  onChange: (value: string) => void;
  className?: string;
}

export default function SearchBar({ placeholder = 'Search...', value, onChange, className = '' }: SearchBarProps) {
  const [local, setLocal] = useState(value);

  useEffect(() => { setLocal(value); }, [value]);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setLocal(e.target.value);
    onChange(e.target.value);
  };

  const handleClear = () => {
    setLocal('');
    onChange('');
  };

  return (
    <div className={`relative ${className}`}>
      <input
        type="text"
        value={local}
        onChange={handleChange}
        placeholder={placeholder}
        className="w-full bg-[#1a1a1a] border border-[#333] rounded-lg px-3 py-2 text-sm text-white placeholder-[#6A6E73] focus:outline-none focus:border-[#555] transition"
      />
      {local && (
        <button
          onClick={handleClear}
          className="absolute right-2 top-1/2 -translate-y-1/2 text-[#6A6E73] hover:text-white text-xs"
        >
          &times;
        </button>
      )}
    </div>
  );
}
