import { useState } from 'react';
import { recent } from './mock/expenses';

// Hook di accesso ai dati: la UI parla solo con questo (decisione D14).
export function useExpenses() {
  const [expenses] = useState(recent);
  return { expenses };
}
