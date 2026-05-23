import 'package:flutter_test/flutter_test.dart';
import 'package:acronous_ai_flutter/main.dart';

void main() {
  testWidgets('App should build', (WidgetTester tester) async {
    await tester.pumpWidget(const AcronousAIApp());
    expect(find.byType(AcronousAIApp), findsOneWidget);
  });
}
