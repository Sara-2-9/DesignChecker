import { Pressable, Text, StyleSheet } from 'react-native';
import { theme } from '../../../theme';
import type { Expense } from '../../../data/mock/expenses';

// Riga di lista — altezza minima 44pt (iOS) / 48dp (Android).
type Props = { item: Expense };

export function ExpenseRow({ item }: Props) {
  return (
    <Pressable style={styles.row} accessibilityRole="button"
      accessibilityLabel={`${item.title} — ${item.amount}`}>
      <View>
        <Text style={styles.title}>{item.title}</Text>
        <Text style={styles.subtitle}>{item.date} · {item.payer}</Text>
      </View>
      <Text style={styles.amount}>{item.amount}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  row: {
    minHeight: 48,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: theme.spacing[4],
    paddingVertical: theme.spacing[2],
    backgroundColor: theme.colors['surface-raised'],
    borderRadius: theme.radius.sm,
  },
  title: { fontSize: theme.typography.body, color: theme.colors['text-primary'] },
  subtitle: { fontSize: theme.typography.caption, color: theme.colors['text-secondary'] },
  amount: { fontSize: theme.typography.body, fontWeight: '600', color: theme.colors['text-primary'] },
});
