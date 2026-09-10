import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';
import { FlatList, Pressable, StyleSheet, Text, View } from 'react-native';
import { theme } from '../../theme';
import { EmptyState } from '../../components/empty-state';
import { ExpenseRow } from './components/expense-row';
import { useExpenses } from '../../data/use-expenses';

export function Home() {
  const router = useRouter();
  const { expenses } = useExpenses();
  return (
  <SafeAreaView style={styles.screenHome}>
    <View style={styles.header} accessibilityRole="header">
      <Text style={styles.headerTitle}>Ciao Sara</Text>
      <Text style={styles.headerSubtitle}>Casa Rossi · 3 membri</Text>
    </View>
    <View style={styles.balanceCard}>
      <Text style={styles.balanceLabel}>Il tuo saldo</Text>
      <Text style={styles.balanceValue} accessibilityLabel="Saldo positivo di 24 euro e 50">+ 24,50 €</Text>
    </View>
    <Text style={styles.recentHeader}>Spese recenti</Text>
    <FlatList
      data={expenses}
      keyExtractor={(item) => item.id}
      renderItem={({ item }) => <ExpenseRow item={item} />}
      contentContainerStyle={styles.expenseList}
      ListEmptyComponent={<EmptyState message="Nessuna spesa ancora" actionLabel="Aggiungi la prima spesa" onAction={() => router.push('/add-expense')} />}
    />
    <Pressable onPress={() => router.push('/add-expense')} accessibilityRole="button" accessibilityLabel="Aggiungi una nuova spesa" style={({ pressed }) => [styles.addExpenseFab, { backgroundColor: theme.colors.brand.primary }, pressed && { opacity: 0.85 }]}>
      <Text style={styles.addExpenseFabLabel}>Aggiungi spesa</Text>
    </Pressable>
    {/* TabBar: renderizzata da src/app/_layout.tsx (Native Tabs) */}
  </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screenHome: {
    backgroundColor: theme.colors.surface,
    paddingHorizontal: theme.spacing['4'],
    flex: 1,
  },
  header: {
    color: theme.colors['text-primary'],
    paddingVertical: theme.spacing['4'],
    alignSelf: 'stretch',
  },
  headerSubtitle: {
    fontSize: theme.typography.body,
    color: theme.colors['text-secondary'],
  },
  headerTitle: {
    fontSize: theme.typography.title,
    fontWeight: '700',
    color: theme.colors['text-primary'],
  },
  balanceCard: {
    backgroundColor: theme.colors['surface-raised'],
    borderRadius: theme.radius.lg,
    padding: theme.spacing['4'],
    gap: theme.spacing['2'],
    alignSelf: 'stretch',
  },
  balanceLabel: {
    color: theme.colors['text-secondary'],
    fontSize: theme.typography.caption,
  },
  balanceValue: {
    color: theme.colors.success,
    fontSize: theme.typography.title,
    fontWeight: '700',
  },
  recentHeader: {
    color: theme.colors['text-primary'],
    paddingTop: theme.spacing['6'],
    paddingBottom: theme.spacing['2'],
    fontSize: theme.typography.heading,
    fontWeight: '700',
  },
  expenseList: {
    gap: theme.spacing['2'],
    alignSelf: 'stretch',
    flex: 1,
  },
  addExpenseFab: {
    backgroundColor: theme.colors.brand.primary,
    position: 'absolute',
    width: 56,
    height: 56,
    borderRadius: 28,
    alignItems: 'center',
    justifyContent: 'center',
    bottom: theme.spacing['4'],
    right: theme.spacing['4'],
  },
  addExpenseFabLabel: {
    color: theme.colors.brand['on-primary'],
    fontSize: theme.typography.body,
    fontWeight: '600',
  }
});
