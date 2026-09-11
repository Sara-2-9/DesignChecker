// Fixture "app legacy" per i test dell'importer codice (D23):
// contiene violazioni tipiche di codice scritto senza design system.
import React from 'react';
import { View, Text, Pressable, StyleSheet } from 'react-native';

export function LegacyScreen() {
  return (
    <View style={styles.screen}>
      <Text style={styles.tiny}>Benvenuto</Text>
      <Pressable style={styles.smallButton} onPress={() => console.log('tap')}>
        <Text>OK</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {
    backgroundColor: '#FF0000',   // hex hardcoded: violazione token
    padding: 13,                  // spacing grezzo non tokenizzato
  },
  tiny: {
    fontSize: 9,                  // sotto il minimo leggibile
    color: '#CCCCCC',             // contrasto probabilmente insufficiente
  },
  smallButton: {
    width: 32,                    // touch target sotto 44pt/48dp
    height: 32,
    backgroundColor: '#0066FF',
  },
});
