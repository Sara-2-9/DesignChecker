import { View, Text, StyleSheet } from 'react-native';
import { Button } from './button';
import { theme } from '../theme';

// HIG empty state: mai schermate vuote, sempre messaggio + azione (ios.empty-state-action).
type Props = {
  message: string;
  actionLabel?: string;
  onAction?: () => void;
};

export function EmptyState({ message, actionLabel, onAction }: Props) {
  return (
    <View style={styles.container}>
      <Text style={styles.message}>{message}</Text>
      {actionLabel ? <Button label={actionLabel} onPress={onAction} /> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    alignItems: 'center',
    justifyContent: 'center',
    padding: theme.spacing[6],
    gap: theme.spacing[4],
  },
  message: {
    fontSize: theme.typography.body,
    color: theme.colors['text-secondary'],
    textAlign: 'center',
  },
});
