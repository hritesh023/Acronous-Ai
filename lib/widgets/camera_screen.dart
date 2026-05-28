import 'package:camera/camera.dart';
import 'package:flutter/material.dart';

enum CameraResult { success, error, noCamera, cancelled }

class CameraScreen extends StatefulWidget {
  const CameraScreen({super.key});

  @override
  State<CameraScreen> createState() => _CameraScreenState();
}

class _CameraScreenState extends State<CameraScreen>
    with WidgetsBindingObserver {
  CameraController? _controller;
  bool _isInitialized = false;
  bool _isCapturing = false;
  bool _isInitializing = false;
  bool _hasError = false;
  String? _errorMessage;
  List<CameraDescription> _cameras = [];
  int _currentCameraIndex = 0;
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _initCamera();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _controller?.dispose();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.inactive && mounted) {
      _controller?.dispose();
      _controller = null;
      _isInitialized = false;
    } else if (state == AppLifecycleState.resumed && mounted) {
      if (_controller == null && !_isInitialized && !_isInitializing) {
        _hasError = false;
        _errorMessage = null;
        _initCamera();
      }
    }
  }

  Future<void> _initCamera() async {
    if (_isInitializing) return;
    _isInitializing = true;
    _hasError = false;
    _errorMessage = null;
    try {
      final cameras = await availableCameras();
      if (!mounted) return;
      if (cameras.isEmpty) {
        setState(() {
          _hasError = true;
          _errorMessage = 'No camera found on this device';
        });
        return;
      }
      _cameras = cameras;
      final controller = CameraController(cameras[0], ResolutionPreset.veryHigh);
      _controller = controller;
      await controller.initialize();
      if (!mounted) {
        controller.dispose();
        return;
      }
      if (_controller != controller) {
        controller.dispose();
        return;
      }
      setState(() => _isInitialized = true);
    } catch (e) {
      if (!mounted) return;
      if (_isInitialized) return;
      setState(() {
        _hasError = true;
        _errorMessage = 'Could not access camera';
      });
    } finally {
      _isInitializing = false;
    }
  }

  Future<void> _switchCamera() async {
    if (_cameras.length < 2) return;
    final newIndex = (_currentCameraIndex + 1) % _cameras.length;
    final oldController = _controller;
    _controller = null;
    _isInitialized = false;
    oldController?.dispose();
    final controller = CameraController(_cameras[newIndex], ResolutionPreset.veryHigh);
    _controller = controller;
    try {
      await controller.initialize();
      _currentCameraIndex = newIndex;
      if (mounted) setState(() => _isInitialized = true);
    } catch (_) {
      _controller = oldController;
      if (mounted) setState(() => _isInitialized = true);
    }
  }

  Future<void> _capture() async {
    if (_controller == null || !_isInitialized || _isCapturing) return;
    _isCapturing = true;
    try {
      final image = await _controller!.takePicture();
      if (!mounted) return;
      FocusManager.instance.primaryFocus?.unfocus();
      Navigator.pop(context, (image.path, CameraResult.success));
    } catch (_) {
      if (!mounted) return;
      FocusManager.instance.primaryFocus?.unfocus();
      Navigator.pop(context, (null, CameraResult.error));
    } finally {
      _isCapturing = false;
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      body: Stack(
        fit: StackFit.expand,
        children: [
          if (_isInitialized && _controller != null)
            ClipRect(
              child: GestureDetector(
                onTap: () async {
                  try {
                    await _controller?.setFocusPoint(null);
                  } catch (_) {}
                },
                child: CameraPreview(_controller!),
              ),
            )
          else if (_hasError)
            _buildErrorState()
          else
            const Center(child: CircularProgressIndicator()),
          if (_isInitialized && _cameras.length > 1)
            Positioned(
              top: 60,
              right: 20,
              child: IconButton(
                icon: const Icon(Icons.flip_camera_ios_rounded,
                    color: Colors.white, size: 28),
                onPressed: _switchCamera,
              ),
            ),
          Positioned(
            bottom: 50,
            left: 0,
            right: 0,
            child: Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                IconButton(
                  icon: const Icon(Icons.close, color: Colors.white, size: 28),
                  onPressed: () {
                    if (!mounted) return;
                    FocusManager.instance.primaryFocus?.unfocus();
                    Navigator.pop(context, (null, CameraResult.cancelled));
                  },
                ),
                const SizedBox(width: 50),
                if (_isInitialized)
                  GestureDetector(
                    onTap: _capture,
                    child: Container(
                      width: 72,
                      height: 72,
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        color: Colors.white,
                        border: Border.all(color: Colors.white70, width: 4),
                      ),
                      child: Container(
                        margin: const EdgeInsets.all(6),
                        decoration: const BoxDecoration(
                          shape: BoxShape.circle,
                          color: Colors.white,
                        ),
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildErrorState() {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.videocam_off_rounded,
                color: Colors.white54, size: 64),
            const SizedBox(height: 16),
            Text(
              _errorMessage ?? 'Could not access camera',
              style: const TextStyle(color: Colors.white70, fontSize: 16),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 24),
            FilledButton.icon(
              onPressed: _isInitializing ? null : () {
                _isInitialized = false;
                _initCamera();
              },
              icon: const Icon(Icons.refresh_rounded),
              label: const Text('Retry'),
            ),
          ],
        ),
      ),
    );
  }
}
