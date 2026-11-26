import 'dart:async';
import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:flutter/foundation.dart';
import '../secrets.dart';

class HardwareService {
  // IP fixe du boîtier : 192.168.100.1
  // Pour tester avec le faux boîtier : --dart-define=WGM_HOST=127.0.0.1:8080
  static const String _baseUrl =
      String.fromEnvironment('WGM_HOST', defaultValue: '192.168.100.1');
  // Clé API (doit correspondre exactement à celle du firmware, voir lib/secrets.dart)
  static const String _secretKey = AppSecrets.apiKey;

  static Future<void> init() async {}

  static String get currentIp => _baseUrl;

  /// Construit l'URL d'une route. Uri.http encode correctement la clé
  /// (le '#' de la clé couperait sinon l'URL et le boîtier ne recevrait que "X9").
  static Uri _uri(String path, [Map<String, String> params = const {}, bool withKey = true]) {
    return Uri.http(_baseUrl, path, {
      ...params,
      if (withKey) 'key': _secretKey,
    });
  }

  /// Envoie une instruction d'activation au boitier ESP32 avec clé de sécurité complexe
  static Future<bool> sendActivation(String posteId, int minutes) async {
    try {
      final response = await http.get(
        _uri('/activate', {'id': posteId, 'time': '$minutes'}),
      ).timeout(const Duration(seconds: 4));

      return response.statusCode == 200;
    } catch (e) {
      debugPrint("Erreur Hardware (Activation): $e");
      return false; 
    }
  }

  /// Envoie une instruction d'arrêt au boitier ESP32 avec clé de sécurité
  static Future<bool> sendDeactivation(String posteId) async {
    try {
      final response = await http.get(
        _uri('/stop', {'id': posteId}),
      ).timeout(const Duration(seconds: 4));

      return response.statusCode == 200;
    } catch (e) {
      debugPrint("Erreur Hardware (Arrêt): $e");
      return false;
    }
  }

  /// Récupère l'état de tous les postes (incluant les coupures)
  static Future<Map<String, dynamic>?> getStatus() async {
    try {
      final response = await http.get(
        _uri('/status', const {}, false),
      ).timeout(const Duration(seconds: 2));

      if (response.statusCode == 200) {
        final data = json.decode(response.body);
        final Map<String, dynamic> statusMap = {};
        for (var poste in data['postes']) {
          statusMap[poste['id']] = {
            'remains': poste['remains'],
            'isCoupure': poste['isCoupure'] ?? false,
          };
        }
        return statusMap;
      }
    } catch (e) {
      // Silence sur les timeouts de status
    }
    return null;
  }

  /// Relance une session après coupure
  static Future<bool> resumeAfterCoupure(String posteId) async {
    try {
      final response = await http.get(
        _uri('/resume', {'id': posteId}),
      ).timeout(const Duration(seconds: 4));

      return response.statusCode == 200;
    } catch (e) {
      debugPrint("Erreur Hardware (Resume): $e");
      return false;
    }
  }

  /// Envoie une mise à jour firmware (.bin)
  static Future<bool> sendUpdate(List<int> bytes) async {
    try {
      // La clé est dans l'URL pour que le boîtier la vérifie avant d'écrire le firmware
      final uri = _uri('/update');
      var request = http.MultipartRequest('POST', uri);
      request.files.add(http.MultipartFile.fromBytes('update', bytes, filename: 'update.bin'));
      
      var response = await request.send().timeout(const Duration(minutes: 5));
      return response.statusCode == 200;
    } catch (e) {
      debugPrint("Erreur Hardware (Mise à jour): $e");
      return false;
    }
  }
}
