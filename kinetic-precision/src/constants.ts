/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

export interface NavItem {
  label: string;
  id: string;
  icon: string;
}

export const NAV_ITEMS: NavItem[] = [
  { label: 'Data Upload', id: 'upload', icon: 'Upload' },
  { label: 'Site Profile', id: 'profile', icon: 'Factory' },
  { label: 'Forecast & Risk', id: 'forecast', icon: 'TrendingUp' },
  { label: 'Optimization', id: 'optimization', icon: 'Zap' },
  { label: 'Executive Summary', id: 'summary', icon: 'BarChart' },
];
