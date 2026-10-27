"""Minimal Eager callbacks copied from frozen v4, without math changes.

Importing this file is CPU-safe. FlashRT constants are injected by the caller.
Actual Encoder/Decoder calls are observed, not inferred from job counts.
"""
from m2_executor import BLOCKS, DECODER, DECODER_CALLS


def context(p, stream=0):
    p._copy_lang_embeds_to_encoder_x(stream=stream);p.vision_encoder(stream);p.transformer_encoder(stream)


def block1(p, ENC_D, VIS_D, stream=0):
    p._copy_lang_embeds_to_encoder_x(stream=stream);p.vision_encoder(stream)
    B,W,fvk,gemm=p.bufs,p.weights,p.fvk,p.gemm;vs=p.vision_seq_enc
    fvk.layer_norm(B['vision_x_pooled'].ptr.value,W['vision_final_norm_w'],W['vision_final_norm_b'],B['vision_x_norm'].ptr.value,vs,VIS_D,1e-5,stream=stream)
    gemm.bf16_nn(B['vision_x_norm'].ptr.value,W['encoder_multi_modal_projector_w'],B['encoder_x'].ptr.value,vs,ENC_D,VIS_D,stream=stream)
    fvk.add_bias_bf16(B['encoder_x'].ptr.value,W['encoder_multi_modal_projector_b'],vs,ENC_D,stream=stream)
    for i in range(9):p._encoder_layer(i,561,False,stream)


def block2(p, stream=0):
    for i in range(9,18):p._encoder_layer(i,561,False,stream)


def prefix_block(p, ENC_D, VIS_D, stream=0):
    """Language + Vision27 + norm/project/bias only: no encoder call, 0 new KV."""
    p._copy_lang_embeds_to_encoder_x(stream=stream);p.vision_encoder(stream)
    B,W,fvk,gemm=p.bufs,p.weights,p.fvk,p.gemm;vs=p.vision_seq_enc
    fvk.layer_norm(B['vision_x_pooled'].ptr.value,W['vision_final_norm_w'],W['vision_final_norm_b'],B['vision_x_norm'].ptr.value,vs,VIS_D,1e-5,stream=stream)
    gemm.bf16_nn(B['vision_x_norm'].ptr.value,W['encoder_multi_modal_projector_w'],B['encoder_x'].ptr.value,vs,ENC_D,VIS_D,stream=stream)
    fvk.add_bias_bf16(B['encoder_x'].ptr.value,W['encoder_multi_modal_projector_b'],vs,ENC_D,stream=stream)


def encoder_block(p, lo, hi, stream=0):
    """Contiguous legal encoder layer group; no other math."""
    for i in range(lo,hi):p._encoder_layer(i,561,False,stream)


class CallLedger:
    def __init__(self, pipelines):
        self.stream_id = 0
        self.calls = []
        self.active = None
        self.original = []
        for slot, p in enumerate(pipelines):
            enc, dec, vis, lang = p._encoder_layer, p._decoder_layer, p.vision_encoder, p._copy_lang_embeds_to_encoder_x
            self.original.append((p, enc, dec, vis, lang))
            def e(i, seq, fuse_b1, stream, orig=enc, s=slot):
                if stream != self.stream_id: raise RuntimeError('unapproved stream')
                self.calls.append((self.active, s, 'encoder', i))
                return orig(i, seq, fuse_b1, stream)
            def d(i, step, enc_seq, ds, skip_c1, stream, orig=dec, s=slot):
                if stream != self.stream_id: raise RuntimeError('unapproved stream')
                self.calls.append((self.active, s, 'decoder', step, i))
                return orig(i, step, enc_seq, ds, skip_c1, stream)
            def v(stream=0, orig=vis, s=slot):
                if stream != self.stream_id: raise RuntimeError('unapproved stream')
                self.calls.append((self.active, s, 'vision27'))
                return orig(stream)
            def l(stream=0, orig=lang, s=slot):
                if stream != self.stream_id: raise RuntimeError('unapproved stream')
                self.calls.append((self.active, s, 'language'))
                return orig(stream=stream)
            p._encoder_layer, p._decoder_layer = e, d
            p.vision_encoder, p._copy_lang_embeds_to_encoder_x = v, l

    def execute(self, key, slot, kind, fn, expected=None, work=None):
        """``expected``/``work`` let a reviewed block plan declare its own legal
        call sequence instead of the frozen two-block vocabulary."""
        if self.active is not None: raise RuntimeError('nested model operation')
        start = len(self.calls)
        self.active = key
        try: fn()
        finally: self.active = None
        rows = self.calls[start:]
        if any(row[1] != slot for row in rows): raise RuntimeError('wrong slot')
        actual = [row[2:] for row in rows]
        if expected is None:
            expected = ([('language',), ('vision27',)] + [('encoder', i) for i in range(9)] if kind == 'B1'
                        else [('encoder', i) for i in range(9, 18)] if kind == 'B2'
                        else list(DECODER_CALLS) if kind == 'Expert'
                        else [('language',), ('vision27',)] + [('encoder', i) for i in range(18)])
        if actual != expected: raise RuntimeError('incomplete/repeated real model calls')
        if work is not None: return tuple(work)
        return DECODER if kind == 'Expert' else BLOCKS[0 if kind == 'B1' else 1]
