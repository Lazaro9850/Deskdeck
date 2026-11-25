// Auxiliar de audio do Painel PC (Core Audio via COM), compilado em um .exe pequeno.
// Substitui o audio_helper.ps1: faz o mesmo usando ~6 MB de RAM em vez de ~60 MB do PowerShell.
// Le comandos por stdin (um por linha) e responde uma linha JSON:
//   state     -> {"vol":75,"muted":false,"mic_muted":false}
//   togglemic -> {"mic_muted":true}
// Compilar: csc.exe /nologo /optimize /target:exe /out:audio_helper.exe audio_helper.cs
using System;
using System.Runtime.InteropServices;

namespace PainelAudio {
  [ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")] class MMDeviceEnumeratorCom {}
  [Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IMMDeviceEnumerator {
    int EnumAudioEndpoints(int dataFlow, int stateMask, out IntPtr devices);
    [PreserveSig] int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice device);
  }
  [Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IMMDevice {
    [PreserveSig] int Activate(ref Guid iid, int clsCtx, IntPtr activationParams, [MarshalAs(UnmanagedType.IUnknown)] out object iface);
  }
  [Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IAudioEndpointVolume {
    int RegisterControlChangeNotify(IntPtr n);
    int UnregisterControlChangeNotify(IntPtr n);
    int GetChannelCount(out uint c);
    int SetMasterVolumeLevel(float db, IntPtr ctx);
    int SetMasterVolumeLevelScalar(float level, IntPtr ctx);
    int GetMasterVolumeLevel(out float db);
    int GetMasterVolumeLevelScalar(out float level);
    int SetChannelVolumeLevel(uint ch, float db, IntPtr ctx);
    int SetChannelVolumeLevelScalar(uint ch, float level, IntPtr ctx);
    int GetChannelVolumeLevel(uint ch, out float db);
    int GetChannelVolumeLevelScalar(uint ch, out float level);
    int SetMute([MarshalAs(UnmanagedType.Bool)] bool mute, IntPtr ctx);
    int GetMute([MarshalAs(UnmanagedType.Bool)] out bool mute);
  }

  static class Program {
    static IAudioEndpointVolume Ep(int flow) {
      var en = (IMMDeviceEnumerator)(new MMDeviceEnumeratorCom());
      IMMDevice dev;
      if (en.GetDefaultAudioEndpoint(flow, 0 /* eConsole */, out dev) != 0 || dev == null) return null;
      Guid iid = typeof(IAudioEndpointVolume).GUID;
      object o;
      if (dev.Activate(ref iid, 23 /* CLSCTX_ALL */, IntPtr.Zero, out o) != 0) return null;
      return (IAudioEndpointVolume)o;
    }
    static string State() {
      var sp = Ep(0); var mic = Ep(1);
      string vol = "null", muted = "null", micm = "null";
      if (sp != null) { float v; bool m; sp.GetMasterVolumeLevelScalar(out v); sp.GetMute(out m);
        vol = ((int)Math.Round(v * 100)).ToString(); muted = m ? "true" : "false"; }
      if (mic != null) { bool m; mic.GetMute(out m); micm = m ? "true" : "false"; }
      return "{\"vol\":" + vol + ",\"muted\":" + muted + ",\"mic_muted\":" + micm + "}";
    }
    static string ToggleMic() {
      var mic = Ep(1);
      if (mic == null) return "{\"mic_muted\":null}";
      bool m; mic.GetMute(out m); mic.SetMute(!m, IntPtr.Zero);
      return "{\"mic_muted\":" + (!m ? "true" : "false") + "}";
    }
    [STAThread]
    static void Main() {
      Console.Out.WriteLine("{\"ready\":true}"); Console.Out.Flush();
      string line;
      while ((line = Console.In.ReadLine()) != null) {
        string r;
        try {
          // EndsWith: ignora uma marca BOM no inicio, venha ela como caractere ou como bytes soltos
          string cmd = line.Trim();
          if (cmd.EndsWith("togglemic")) r = ToggleMic();
          else if (cmd.EndsWith("state")) r = State();
          else r = "{\"err\":\"comando\"}";
        } catch (Exception e) {
          r = "{\"err\":\"" + e.Message.Replace("\"", " ").Replace("\\", " ").Replace("\r", " ").Replace("\n", " ") + "\"}";
        }
        Console.Out.WriteLine(r); Console.Out.Flush();
      }
    }
  }
}
