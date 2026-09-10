import { Pressable, Text, StyleSheet } from 'react-native';
import { theme } from '../theme';

// Componente dalla component library DesignChecker (catalogo: Button).
// Conforme per costruzione: minHeight 48 (M3), Pressable, label sempre presente.
type Props = {
  label: string;
  onPress?: () => void;
  variant?: 'primary' | 'secondary' | 'destructive';
  accessibilityLabel?: string;
};

export function Button({ label, onPress, variant = 'primary', accessibilityLabel }: Props) {
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel ?? label}
      style={({ pressed }) => [styles.base, styles[variant], pressed && styles.pressed]}
    >
      <Text style={[styles.label, variant === 'secondary' && styles.labelOnSecondary]}>
        {label}
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  base: {
    minHeight: 48,
    borderRadius: theme.radius.sm,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: theme.spacing[4],
  },
  primary: { backgroundColor: theme.colors.brand.primary },
  secondary: { backgroundColor: theme.colors.neutral[200] },
  destructive: { backgroundColor: theme.colors.error },
  pressed: { opacity: 0.85 },
  label: {
    color: theme.colors.brand['on-primary'],
    fontSize: theme.typography.body,
    fontWeight: '600',
  },
  labelOnSecondary: { color: theme.colors['text-primary'] },
});
