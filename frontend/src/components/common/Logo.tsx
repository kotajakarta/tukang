import React from 'react';

/** Brand mark (white disc keeps the black/white logo legible on both themes). */
export const Logo: React.FC<{ size?: number; className?: string }> = ({ size = 36, className = '' }) => (
  <img
    src="/logo.png"
    alt="tuKang"
    width={size}
    height={size}
    className={`rounded-full ring-1 ring-line flex-shrink-0 select-none ${className}`}
    draggable={false}
  />
);
