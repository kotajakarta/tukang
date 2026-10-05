import React from 'react';
import { Segmented, Tooltip } from 'antd';
import { Monitor, Moon, Sun } from 'lucide-react';
import { ThemeMode, useTheme } from '../../context/ThemeContext';

const MODE_META: Record<ThemeMode, { label: string; Icon: typeof Sun }> = {
  system: { label: 'System', Icon: Monitor },
  light: { label: 'Light', Icon: Sun },
  dark: { label: 'Dark', Icon: Moon },
};

const NEXT: Record<ThemeMode, ThemeMode> = { system: 'light', light: 'dark', dark: 'system' };

/** Header icon button: cycles System -> Light -> Dark */
export const ThemeToggle: React.FC = () => {
  const { mode, resolved, cycleMode } = useTheme();
  const { label, Icon } = MODE_META[mode];
  const current = mode === 'system' ? `${label} (${resolved})` : label;

  return (
    <Tooltip title={`Theme: ${current}`} placement="bottom">
      <button
        type="button"
        onClick={cycleMode}
        aria-label={`Theme: ${current}. Switch to ${MODE_META[NEXT[mode]].label.toLowerCase()}`}
        className="focus-ring inline-flex items-center justify-center h-9 w-9 rounded-md bg-transparent text-fg-muted hover:bg-surface-2 hover:text-fg cursor-pointer"
      >
        <Icon size={18} strokeWidth={1.75} />
      </button>
    </Tooltip>
  );
};

/** All three choices side by side (mobile "More" sheet) */
export const ThemeSegmented: React.FC = () => {
  const { mode, setMode } = useTheme();
  return (
    <Segmented<ThemeMode>
      block
      value={mode}
      onChange={setMode}
      options={(Object.keys(MODE_META) as ThemeMode[]).map((m) => {
        const { label, Icon } = MODE_META[m];
        return {
          value: m,
          label: (
            <span className="inline-flex items-center justify-center gap-1.5 py-1">
              <Icon size={15} strokeWidth={1.75} />
              {label}
            </span>
          ),
        };
      })}
    />
  );
};
