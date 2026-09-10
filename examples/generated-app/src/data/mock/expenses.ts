// Mock di esempio — UNICO punto dati del prototipo (regola expo.no-mock-inline).
// Quando arriva il DB vero: si sostituisce solo src/data/, la UI non cambia.
export type Expense = {
  id: string;
  title: string;
  amount: string;
  payer: string;
  date: string;
};

export const recent: Expense[] = [
  { id: '1', title: 'Spesa supermercato', amount: '42,30 €', payer: 'Sara', date: '9 set' },
  { id: '2', title: 'Bolletta luce', amount: '58,10 €', payer: 'Marco', date: '7 set' },
  { id: '3', title: 'Pizza condivisa', amount: '27,00 €', payer: 'Giulia', date: '5 set' },
];
